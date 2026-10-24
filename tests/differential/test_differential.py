"""Engine vs. reference on the same random commands: events and depth must match.

Use `pytest --hypothesis-show-statistics` to see how often examples trade.
"""

from collections import Counter
from dataclasses import dataclass

from hypothesis import event, given, settings
from hypothesis import strategies as st
from reference.naive_engine import NaiveEngine

from matching_engine.engine import Engine
from matching_engine.events import Cancelled, CancelPurpose, Event, Rejected, Trade
from matching_engine.types import OrderId, Side, StpId, StpPolicy
from tests.invariants.checker import InvariantChecker


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


@st.composite
def _weighted[T](draw: st.DrawFn, *pairs: tuple[int, st.SearchStrategy[T]]) -> T:
    # one_of can't be weighted, so pick an index into a weight-repeated table.
    # List the common branch first: shrinking pulls the index toward 0.
    table = [strategy for weight, strategy in pairs for _ in range(weight)]
    return draw(table[draw(st.integers(0, len(table) - 1))])


# Not positive, not an int, or an int subclass that SPEC rejects (bool).
invalid_numbers = st.one_of(st.integers(-2, 0), st.floats(), st.booleans())
# Narrow band so orders cross often; ~10% invalid so rejects interleave with trades.
prices = _weighted((9, st.integers(98, 102)), (1, invalid_numbers))
qtys = _weighted((9, st.integers(1, 10)), (1, invalid_numbers))
sides = st.sampled_from(Side)
# Mostly both-set or both-unset; the last branch also yields mismatches.
stp_pairs = st.one_of(
    st.just((None, None)),
    st.tuples(st.sampled_from([StpId(1), StpId(2)]), st.sampled_from(StpPolicy)),
    st.tuples(
        st.sampled_from([None, StpId(1), StpId(2)]),
        st.sampled_from([None, *StpPolicy]),
    ),
)

limits = st.builds(
    lambda side, price, qty, stp: Limit(side, price, qty, *stp),
    sides,
    prices,
    qtys,
    stp_pairs,
)
markets = st.builds(
    lambda side, qty, stp: Market(side, qty, *stp), sides, qtys, stp_pairs
)
# Ids are seqs, so 1..60 overlap live orders; 0 and negatives miss on purpose.
# Non-int ids excluded (SPEC silent, D-09).
cancels = st.builds(Cancel, st.integers(-2, 60).map(OrderId))
# Limits weighted double so the book has something to match against.
commands = st.lists(_weighted((2, limits), (1, markets), (1, cancels)), max_size=60)


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


def _record_coverage(events: list[Event]) -> None:
    # One label per path hit, for --hypothesis-show-statistics.
    if any(isinstance(e, Trade) for e in events):
        event("has trade")
    for purpose in CancelPurpose:
        if any(isinstance(e, Cancelled) and e.purpose is purpose for e in events):
            event(f"has cancel: {purpose.name}")
    if any(isinstance(e, Rejected) for e in events):
        event("has reject")


@given(commands)
def test_engine_matches_reference(cmds: list[Command]) -> None:
    engine, reference = Engine(), NaiveEngine()
    checker = InvariantChecker()
    seen: list[Event] = []
    for step, cmd in enumerate(cmds):
        got = _apply(engine, cmd)
        want = _apply(reference, cmd)
        assert got == want, f"events diverge at step {step}: {cmd}"
        for side in Side:
            assert engine.depth(side) == reference.depth(side), (
                f"{side.name} depth diverges at step {step}: {cmd}"
            )
        _observe(checker, cmd, got)
        checker.check(engine)
        seen.extend(got)
    _record_coverage(seen)


def test_command_mix_exercises_matching() -> None:
    # Guards the generator: the differential test still passes if orders stop
    # crossing. Derandomized runs repeat, but rates shift with import order.
    seen: Counter[str] = Counter()

    @settings(max_examples=200, derandomize=True, database=None)
    @given(commands)
    def run(cmds: list[Command]) -> None:
        engine = Engine()
        events = [e for cmd in cmds for e in _apply(engine, cmd)]
        seen["examples"] += 1
        seen["trade"] += any(isinstance(e, Trade) for e in events)
        seen["stp"] += any(
            isinstance(e, Cancelled) and e.purpose is CancelPurpose.SELF_TRADE_PREVENTED
            for e in events
        )

    run()
    # Floors sit just under the measured rates (26% and 8% on 2026-10-24).
    assert seen["trade"] / seen["examples"] >= 0.20
    assert seen["stp"] / seen["examples"] >= 0.05
