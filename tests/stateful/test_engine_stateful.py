"""Stateful property tests for matching_engine.engine.Engine.

Fuzzes random limit/market/cancel commands (with and without self-trade
prevention) and rebuilds the book from the emitted events alone. After every
command it checks that:

- every event carries the seq of the command that produced it, and every
  command (accepted or rejected, order or cancel) consumes exactly one seq;
- each Trade hits the front of the opposite side (best price, then oldest
  seq) at the resting order's price, and never crosses two orders that
  self-trade prevention should have kept apart;
- an incoming order's quantity is fully accounted for: filled + rested or
  cancelled == submitted;
- the event-rebuilt book matches the engine's depth, the engine's book is
  never crossed, and is_resting agrees with the rebuilt book.
"""

from dataclasses import dataclass

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from matching_engine.engine import Engine
from matching_engine.events import (
    Cancelled,
    CancelPurpose,
    Event,
    Rejected,
    Rested,
    Trade,
)
from matching_engine.types import OrderId, Price, Side, StpId, StpPolicy

sides = st.sampled_from([Side.BUY, Side.SELL])
stp_ids = st.sampled_from([None, StpId(1), StpId(2)])
stp_policies = st.sampled_from([None, StpPolicy.CANCEL_NEWEST, StpPolicy.CANCEL_OLDEST])


@dataclass
class _Resting:
    side: Side
    price: Price
    remaining: int
    seq: int
    stp_id: StpId | None


@dataclass
class _Incoming:
    id: OrderId
    side: Side
    qty: int
    stp_id: StpId | None
    stp_policy: StpPolicy | None


class EngineStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.engine = Engine()
        self.model: dict[OrderId, _Resting] = {}
        self.stp_of: dict[OrderId, StpId | None] = {}
        self.seq = 0

    def _front(self, side: Side) -> OrderId | None:
        candidates = [(oid, o) for oid, o in self.model.items() if o.side is side]
        if not candidates:
            return None
        sign = -1 if side is Side.BUY else 1
        return min(candidates, key=lambda c: (sign * c[1].price, c[1].seq))[0]

    def _check_seq(self, events: list[Event]) -> None:
        self.seq += 1
        assert events, "every command must emit at least one event"
        assert all(e.seq == self.seq for e in events)
        if any(isinstance(e, Rejected) for e in events):
            assert len(events) == 1

    def _apply_new_order(self, events: list[Event], incoming: _Incoming) -> None:
        self._check_seq(events)
        if isinstance(events[0], Rejected):
            return
        self.stp_of[incoming.id] = incoming.stp_id
        opposite = Side.SELL if incoming.side is Side.BUY else Side.BUY
        filled = 0
        terminal = 0
        for event in events:
            if isinstance(event, Trade):
                front = self._front(opposite)
                assert event.resting_order_id == front
                resting = self.model[front]
                assert event.incoming_order_id == incoming.id
                assert event.aggressor_side is incoming.side
                assert event.price == resting.price
                assert 0 < event.qty <= resting.remaining
                if incoming.stp_id is not None and incoming.stp_policy is not None:
                    assert resting.stp_id != incoming.stp_id
                resting.remaining -= event.qty
                if resting.remaining == 0:
                    del self.model[front]
                filled += event.qty
            elif isinstance(event, Cancelled) and event.order_id != incoming.id:
                assert event.purpose is CancelPurpose.SELF_TRADE_PREVENTED
                assert incoming.stp_policy is StpPolicy.CANCEL_OLDEST
                assert event.order_id == self._front(opposite)
                resting = self.model.pop(event.order_id)
                assert resting.stp_id == incoming.stp_id
                assert event.remaining == resting.remaining
            elif isinstance(event, Cancelled):
                terminal += 1
                assert event.remaining == incoming.qty - filled
            else:
                assert isinstance(event, Rested)
                terminal += 1
                assert event.order_id == incoming.id
                assert event.side is incoming.side
                assert event.remaining == incoming.qty - filled
                self.model[incoming.id] = _Resting(
                    incoming.side,
                    event.price,
                    event.remaining,
                    event.seq,
                    incoming.stp_id,
                )
        assert filled <= incoming.qty
        assert terminal == (0 if filled == incoming.qty else 1)

    @rule(
        side=sides,
        price=st.integers(min_value=1, max_value=6),
        qty=st.integers(min_value=1, max_value=5),
        stp_id=stp_ids,
        stp_policy=stp_policies,
    )
    def submit_limit(
        self,
        side: Side,
        price: int,
        qty: int,
        stp_id: StpId | None,
        stp_policy: StpPolicy | None,
    ) -> None:
        events = self.engine.submit_limit_order(
            side, price, qty, stp_id=stp_id, stp_policy=stp_policy
        )
        incoming = _Incoming(OrderId(self.seq + 1), side, qty, stp_id, stp_policy)
        self._apply_new_order(events, incoming)

    @rule(
        side=sides,
        qty=st.integers(min_value=1, max_value=8),
        stp_id=stp_ids,
        stp_policy=stp_policies,
    )
    def submit_market(
        self,
        side: Side,
        qty: int,
        stp_id: StpId | None,
        stp_policy: StpPolicy | None,
    ) -> None:
        events = self.engine.submit_market_order(
            side, qty, stp_id=stp_id, stp_policy=stp_policy
        )
        incoming = _Incoming(OrderId(self.seq + 1), side, qty, stp_id, stp_policy)
        self._apply_new_order(events, incoming)
        assert all(not isinstance(e, Rested) for e in events)

    @rule(order_id=st.integers(min_value=1, max_value=40))
    def cancel(self, order_id: int) -> None:
        oid = OrderId(order_id)
        events = self.engine.cancel(oid)
        self._check_seq(events)
        if oid in self.model:
            resting = self.model.pop(oid)
            assert events == [
                Cancelled(
                    order_id=oid,
                    remaining=resting.remaining,  # type: ignore[arg-type]
                    purpose=CancelPurpose.REQUESTED,
                    seq=self.seq,  # type: ignore[arg-type]
                )
            ]
        else:
            assert isinstance(events[0], Rejected)

    @invariant()
    def event_rebuilt_book_matches_engine_depth(self) -> None:
        for side in (Side.BUY, Side.SELL):
            totals: dict[Price, int] = {}
            for o in self.model.values():
                if o.side is side:
                    totals[o.price] = totals.get(o.price, 0) + o.remaining
            expected = sorted(totals.items(), reverse=(side is Side.BUY))
            assert self.engine.depth(side) == expected

    @invariant()
    def book_is_never_crossed(self) -> None:
        bid, ask = self.engine.best_bid(), self.engine.best_ask()
        assert bid is None or ask is None or bid < ask

    @invariant()
    def is_resting_agrees_with_event_rebuilt_book(self) -> None:
        for oid in self.stp_of:
            assert self.engine.is_resting(oid) == (oid in self.model)


TestEngineStateMachine = EngineStateMachine.TestCase
