"""Replays a logged command stream deterministically.

Log format v1 (JSONL): a header line {"format", "seed", "n"}, then one command
per line. Usage: python -m sim.replay logs/<file>
"""

import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

from reference.naive_engine import NaiveEngine
from tests.invariants.checker import InvariantChecker

from matching_engine.engine import Engine
from matching_engine.events import Event
from matching_engine.types import Side, StpPolicy
from sim.generator import Cancel, Command, Limit, Market

FORMAT = 1
_COMMANDS = {cls.__name__: cls for cls in (Limit, Market, Cancel)}
_ENUMS: dict[str, type[Enum]] = {cls.__name__: cls for cls in (Side, StpPolicy)}


def _enc(value: object) -> object:
    # Tagged, so Side.BUY and the invalid string "buy" differ on disk.
    if isinstance(value, Enum):
        return {"enum": type(value).__name__, "name": value.name}
    return value


def _dec(value: Any) -> Any:
    if isinstance(value, dict):
        return _ENUMS[value["enum"]][value["name"]]
    return value


def encode(cmd: Command) -> str:
    fields = {key: _enc(value) for key, value in vars(cmd).items()}
    return json.dumps({"t": type(cmd).__name__, **fields})


def decode(line: str) -> Command:
    raw = json.loads(line)
    cls = _COMMANDS[raw.pop("t")]
    return cls(**{key: _dec(value) for key, value in raw.items()})


def write_log(path: Path, commands: list[Command], seed: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = json.dumps({"format": FORMAT, "seed": seed, "n": len(commands)})
    path.write_text("\n".join([header, *map(encode, commands)]) + "\n")


def read_log(path: Path) -> list[Command]:
    header, *lines = path.read_text().splitlines()
    meta = json.loads(header)
    if meta["format"] != FORMAT:
        raise ValueError(f"{path}: unsupported log format {meta['format']}")
    if len(lines) != meta["n"]:
        raise ValueError(
            f"{path}: header says {meta['n']} commands, found {len(lines)}"
        )
    return [decode(line) for line in lines]


@dataclass(frozen=True)
class Divergence:
    step: int
    command: Command
    reason: str


def _apply(engine: Any, cmd: Command) -> list[Event]:
    # `engine` is Any: invalid types are deliberate (SPEC rejects, never raises).
    match cmd:
        case Limit(side, price, qty, stp_id, stp_policy):
            return cast(
                "list[Event]",
                engine.submit_limit_order(
                    side, price, qty, stp_id=stp_id, stp_policy=stp_policy
                ),
            )
        case Market(side, qty, stp_id, stp_policy):
            return cast(
                "list[Event]",
                engine.submit_market_order(
                    side, qty, stp_id=stp_id, stp_policy=stp_policy
                ),
            )
        case Cancel(order_id):
            return cast("list[Event]", engine.cancel(order_id))


def _observe(checker: InvariantChecker, cmd: Command, events: list[Event]) -> None:
    match cmd:
        case Limit(side, price, qty, stp_id, stp_policy):
            checker.observe_order(side, price, qty, stp_id, stp_policy, events)  # type: ignore[arg-type]
        case Market(side, qty, stp_id, stp_policy):
            checker.observe_order(side, None, qty, stp_id, stp_policy, events)  # type: ignore[arg-type]
        case Cancel(order_id):
            checker.observe_cancel(order_id, events)  # type: ignore[arg-type]


def check(commands: list[Command]) -> Divergence | None:
    """Run engine, reference and invariants in lockstep; return the first failure."""
    engine, reference, checker = Engine(), NaiveEngine(), InvariantChecker()
    for step, cmd in enumerate(commands):
        try:
            got, want = _apply(engine, cmd), _apply(reference, cmd)
            if got != want:
                return Divergence(step, cmd, f"events differ: {got} != {want}")
            for side in Side:
                if engine.depth(side) != reference.depth(side):
                    return Divergence(step, cmd, f"{side.name} depth differs")
            _observe(checker, cmd, got)
            checker.check(engine)
        except Exception as exc:  # an engine or invariant failure is a divergence
            return Divergence(step, cmd, f"{type(exc).__name__}: {exc}")
    return None


def describe(divergence: Divergence) -> str:
    return f"  step {divergence.step}: {divergence.reason}\n  {divergence.command}"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        raise SystemExit("usage: python -m sim.replay logs/<file>")
    commands = read_log(Path(argv[0]))
    divergence = check(commands)
    if divergence is None:
        print(f"ok: {len(commands)} commands")
        return 0
    print(describe(divergence))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
