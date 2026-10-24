"""Seeded long runs and determinism. Failures name a seed and step to reproduce."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from reference.naive_engine import NaiveEngine
from sim.generator import Cancel, Command, Limit, Market, generate

from matching_engine.engine import Engine
from matching_engine.events import Event
from tests.invariants.checker import InvariantChecker

REPO_ROOT = Path(__file__).resolve().parents[2]


def _apply(engine: Engine | NaiveEngine, cmd: Command) -> list[Event]:
    match cmd:
        case Limit(side, price, qty, stp_id, stp_policy):
            # Floats are deliberate (SPEC rejects them); the API says int.
            return engine.submit_limit_order(
                side,
                price,  # type: ignore[arg-type]
                qty,  # type: ignore[arg-type]
                stp_id=stp_id,
                stp_policy=stp_policy,
            )
        case Market(side, qty, stp_id, stp_policy):
            return engine.submit_market_order(
                side,
                qty,  # type: ignore[arg-type]
                stp_id=stp_id,
                stp_policy=stp_policy,
            )
        case Cancel(order_id):
            return engine.cancel(order_id)


def _observe(checker: InvariantChecker, cmd: Command, events: list[Event]) -> None:
    match cmd:
        case Limit(side, price, qty, stp_id, stp_policy):
            checker.observe_order(side, price, qty, stp_id, stp_policy, events)
        case Market(side, qty, stp_id, stp_policy):
            checker.observe_order(side, None, qty, stp_id, stp_policy, events)
        case Cancel(order_id):
            checker.observe_cancel(order_id, events)


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(20))
def test_seeded_run_holds_invariants_and_matches_reference(seed: int) -> None:
    # 20 seeds x 5,000 = the 100k operations in the done criteria.
    engine, reference, checker = Engine(), NaiveEngine(), InvariantChecker()
    for step, cmd in enumerate(generate(seed, 5_000)):
        got = _apply(engine, cmd)
        assert got == _apply(reference, cmd), f"seed {seed} step {step}: {cmd}"
        try:
            _observe(checker, cmd, got)
            checker.check(engine)
        except AssertionError as e:
            raise AssertionError(f"seed {seed} step {step}: {cmd}") from e


def _events_for(seed: int, n: int) -> list[list[Event]]:
    engine = Engine()
    return [_apply(engine, cmd) for cmd in generate(seed, n)]


def test_same_commands_give_same_events() -> None:
    # 7: two fresh engines, same events.
    assert _events_for(7, 2_000) == _events_for(7, 2_000)


# Prints a fixed run's events, to compare across processes.
_SCRIPT = (
    "from tests.invariants.test_seeded_runs import _events_for; "
    "print(repr(_events_for(7, 2_000)))"
)


def test_events_do_not_depend_on_hash_seed() -> None:
    # 7: str/Enum hashes vary with PYTHONHASHSEED, exposing any hash-order dependence.
    outputs = {
        subprocess.run(
            [sys.executable, "-c", _SCRIPT],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONHASHSEED": str(hash_seed)},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for hash_seed in (0, 1, 2)
    }
    assert len(outputs) == 1
