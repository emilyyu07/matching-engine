"""Seeded command generator: the same (seed, n) always gives the same list."""

import random
from dataclasses import dataclass

from matching_engine.types import OrderId, Side, StpId, StpPolicy


@dataclass(frozen=True)
class Limit:
    side: Side
    price: int | float
    qty: int | float
    stp_id: StpId | None
    stp_policy: StpPolicy | None


@dataclass(frozen=True)
class Market:
    side: Side
    qty: int | float
    stp_id: StpId | None
    stp_policy: StpPolicy | None


@dataclass(frozen=True)
class Cancel:
    order_id: OrderId


Command = Limit | Market | Cancel

# Rare invalid inputs interleave rejects (and their seq gaps) with trades.
_INVALID_NUMBERS: list[int | float] = [0, -1, 1.5, True]


def _number(rng: random.Random, lo: int, hi: int) -> int | float:
    if rng.random() < 0.05:
        return rng.choice(_INVALID_NUMBERS)
    return rng.randint(lo, hi)


def _stp(rng: random.Random) -> tuple[StpId | None, StpPolicy | None]:
    roll = rng.random()
    if roll < 0.70:
        return None, None
    if roll < 0.95:
        return StpId(rng.randint(1, 2)), rng.choice(list(StpPolicy))
    # Half-set pair: must be rejected.
    return rng.choice([(StpId(1), None), (None, StpPolicy.CANCEL_NEWEST)])


def _cancel_target(rng: random.Random, seq: int) -> OrderId:
    # Ids are seqs, so recent seqs often hit live orders; some ids can't be resting.
    if seq == 1 or rng.random() < 0.10:
        return OrderId(rng.choice([-1, 0, seq, seq + 100]))
    return OrderId(rng.randint(max(1, seq - 50), seq - 1))


def generate(seed: int, n: int) -> list[Command]:
    """50% limit, 25% market, 25% cancel, on a narrow price band so orders cross."""
    rng = random.Random(seed)
    commands: list[Command] = []
    for seq in range(1, n + 1):
        roll = rng.random()
        side = rng.choice([Side.BUY, Side.SELL])
        if roll < 0.50:
            price, qty = _number(rng, 95, 105), _number(rng, 1, 10)
            commands.append(Limit(side, price, qty, *_stp(rng)))
        elif roll < 0.75:
            commands.append(Market(side, _number(rng, 1, 10), *_stp(rng)))
        else:
            commands.append(Cancel(_cancel_target(rng, seq)))
    return commands
