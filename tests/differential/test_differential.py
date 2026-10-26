"""Engine vs. reference on the same random commands: events and depth must match.

Use `pytest --hypothesis-show-statistics` to see how often examples trade.
"""

from collections import Counter
from dataclasses import dataclass

from hypothesis import event, given, note, settings
from hypothesis import strategies as st
from reference.naive_engine import NaiveEngine

from matching_engine.engine import Engine
from matching_engine.events import Cancelled, CancelPurpose, Event, Rejected, Trade
from matching_engine.types import OrderId, Side, StpId, StpPolicy
from tests.invariants.checker import InvariantChecker


@dataclass(frozen=True)
class Limit:
    side: Side | str | None
    price: int | float
    qty: int | float
    stp_id: StpId | float | str | None
    stp_policy: StpPolicy | str | None


@dataclass(frozen=True)
class Market:
    side: Side | str | None
    qty: int | float
    stp_id: StpId | float | str | None
    stp_policy: StpPolicy | str | None


@dataclass(frozen=True)
class Cancel:
    order_id: OrderId | float


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
# Rarely a wrong type: "buy" is Side.BUY's value, not Side.BUY.
sides = _weighted((19, st.sampled_from(Side)), (1, st.sampled_from(["buy", None])))
# Valid groups include 0 and negatives (D-09 B: any exact int).
stp_ids = st.sampled_from([StpId(1), StpId(2), StpId(0), StpId(-1)])
# Mostly both-set or both-unset; then mismatches, then wrong types per field.
stp_pairs = _weighted(
    (3, st.just((None, None))),
    (3, st.tuples(stp_ids, st.sampled_from(StpPolicy))),
    (3, st.tuples(st.one_of(st.none(), stp_ids), st.sampled_from([None, *StpPolicy]))),
    (
        1,
        st.tuples(
            st.sampled_from([True, 1.5, "1"]), st.sampled_from([None, *StpPolicy])
        ),
    ),
    (1, st.tuples(st.one_of(st.none(), stp_ids), st.just("cancel_newest"))),
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
# Never-issued ids, including 0 and negatives.
blind_ids = st.integers(-2, 70).map(OrderId)


def _cancels(checker: InvariantChecker) -> st.SearchStrategy[Cancel]:
    # Mostly live orders; some finished (filled/cancelled) and blind ids for rejects.
    pairs = [(1, blind_ids)]
    if finished := checker.finished_ids():
        pairs.insert(0, (1, st.sampled_from(finished)))
    if resting := checker.resting_ids():
        pairs.insert(0, (5, st.sampled_from(resting)))
        # A live id as a float equals and hashes like it, but must be rejected.
        pairs.append((1, st.sampled_from(resting).map(float)))
    return st.builds(Cancel, _weighted(*pairs))


def _command(checker: InvariantChecker) -> st.SearchStrategy[Command]:
    # Limits weighted double so the book has something to match against.
    return _weighted((2, limits), (1, markets), (1, _cancels(checker)))


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


def _drive(data: st.DataObject, reference: NaiveEngine | None) -> list[Event]:
    """Draw and run up to 60 commands, comparing with `reference` if given."""
    engine, checker = Engine(), InvariantChecker()
    cmds: list[Command] = []
    seen: list[Event] = []
    try:
        for step in range(data.draw(st.integers(0, 60))):
            # Drawn against the current book, so cancels can target live orders.
            cmd = data.draw(_command(checker))
            cmds.append(cmd)
            got = _apply(engine, cmd)
            if reference is not None:
                want = _apply(reference, cmd)
                assert got == want, f"events diverge at step {step}: {cmd}"
                for side in Side:
                    assert engine.depth(side) == reference.depth(side), (
                        f"{side.name} depth diverges at step {step}: {cmd}"
                    )
            _observe(checker, cmd, got)
            checker.check(engine)
            seen.extend(got)
    finally:
        # A failure prints the resolved command list: a ready repro.
        note(f"commands = {cmds}")
    return seen


@given(st.data())
def test_engine_matches_reference(data: st.DataObject) -> None:
    _record_coverage(_drive(data, NaiveEngine()))


def test_command_mix_exercises_matching() -> None:
    # Guards the generator: the differential test still passes if orders stop
    # crossing. Derandomized runs repeat, but rates shift with import order.
    seen: Counter[str] = Counter()

    @settings(max_examples=200, derandomize=True, database=None)
    @given(st.data())
    def run(data: st.DataObject) -> None:
        events = _drive(data, reference=None)
        seen["examples"] += 1
        seen["trade"] += any(isinstance(e, Trade) for e in events)
        for purpose in (CancelPurpose.SELF_TRADE_PREVENTED, CancelPurpose.REQUESTED):
            seen[purpose.name] += any(
                isinstance(e, Cancelled) and e.purpose is purpose for e in events
            )

    run()
    # Far below typical (~80% trade, ~50% STP, ~80% cancel): catches a collapse.
    assert seen["trade"] / seen["examples"] >= 0.15
    assert seen["SELF_TRADE_PREVENTED"] / seen["examples"] >= 0.04
    assert seen["REQUESTED"] / seen["examples"] >= 0.30
