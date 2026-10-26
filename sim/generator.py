"""Seeded command generator: the same (seed, n) always gives the same list."""

import random
from dataclasses import dataclass

from matching_engine.types import OrderId, Side, StpId, StpPolicy


@dataclass(frozen=True)
class Limit:
    side: Side | str
    price: int | float
    qty: int | float
    stp_id: StpId | float | None
    stp_policy: StpPolicy | str | None


@dataclass(frozen=True)
class Market:
    side: Side | str
    qty: int | float
    stp_id: StpId | float | None
    stp_policy: StpPolicy | str | None


@dataclass(frozen=True)
class Cancel:
    order_id: OrderId | float


Command = Limit | Market | Cancel

# Rare invalid inputs interleave rejects (and their seq gaps) with trades.
_INVALID_NUMBERS: list[int | float] = [0, -1, 1.5, True]


def _number(rng: random.Random, lo: int, hi: int) -> int | float:
    if rng.random() < 0.05:
        return rng.choice(_INVALID_NUMBERS)
    return rng.randint(lo, hi)


def _side(rng: random.Random) -> Side | str:
    # Rarely "buy": Side.BUY's value, not Side.BUY, so it must be rejected.
    return "buy" if rng.random() < 0.02 else rng.choice([Side.BUY, Side.SELL])


def _stp(
    rng: random.Random,
) -> tuple[StpId | float | None, StpPolicy | str | None]:
    roll = rng.random()
    if roll < 0.70:
        return None, None
    if roll < 0.93:
        # Groups include 0 and negatives (D-09 B: any exact int).
        return StpId(rng.randint(-1, 2)), rng.choice(list(StpPolicy))
    if roll < 0.97:
        # Half-set pair: must be rejected.
        return rng.choice([(StpId(1), None), (None, StpPolicy.CANCEL_NEWEST)])
    # Wrong type for one field: must be rejected.
    return rng.choice([(1.0, StpPolicy.CANCEL_NEWEST), (StpId(1), "cancel_newest")])


def _cancel_target(rng: random.Random, seq: int) -> OrderId | float:
    # Ids are seqs, so recent seqs often hit live orders; some ids can't be resting.
    if seq == 1 or rng.random() < 0.10:
        return OrderId(rng.choice([-1, 0, seq, seq + 100]))
    target = OrderId(rng.randint(max(1, seq - 50), seq - 1))
    # As a float it equals a possibly-live id, but must never cancel it.
    return float(target) if rng.random() < 0.03 else target


def generate(seed: int, n: int) -> list[Command]:
    """50% limit, 25% market, 25% cancel, on a narrow price band so orders cross."""
    rng = random.Random(seed)
    commands: list[Command] = []
    for seq in range(1, n + 1):
        roll = rng.random()
        side = _side(rng)
        if roll < 0.50:
            price, qty = _number(rng, 95, 105), _number(rng, 1, 10)
            commands.append(Limit(side, price, qty, *_stp(rng)))
        elif roll < 0.75:
            commands.append(Market(side, _number(rng, 1, 10), *_stp(rng)))
        else:
            commands.append(Cancel(_cancel_target(rng, seq)))
    return commands
