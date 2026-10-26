"""Engine invariants (PROJECT.md section 6), checked on a book rebuilt from events."""

from dataclasses import dataclass

from matching_engine.book import OrderHandle
from matching_engine.engine import Engine
from matching_engine.events import (
    Cancelled,
    CancelPurpose,
    Event,
    Rejected,
    Rested,
    Trade,
)
from matching_engine.types import OrderId, Side, StpId, StpPolicy


@dataclass
class _Resting:
    side: Side
    price: int
    remaining: int
    seq: int
    stp_id: StpId | None


@dataclass
class _Ledger:
    # Where an accepted order's quantity has gone.
    qty: int
    filled: int = 0
    cancelled: int = 0


def _opposite(side: Side) -> Side:
    return Side.SELL if side is Side.BUY else Side.BUY


def _marketable(side: Side, limit: int | None, resting_price: int) -> bool:
    # Market orders (no limit) always match; equal prices match.
    if limit is None:
        return True
    return resting_price <= limit if side is Side.BUY else resting_price >= limit


class InvariantChecker:
    def __init__(self) -> None:
        self._book: dict[OrderId, _Resting] = {}
        self._ledger: dict[OrderId, _Ledger] = {}

    def resting_ids(self) -> list[OrderId]:
        return sorted(self._book)

    def finished_ids(self) -> list[OrderId]:
        # Accepted but no longer resting: filled, cancelled, or a market order.
        return sorted(oid for oid in self._ledger if oid not in self._book)

    def _check_conservation(self, order_ids: set[OrderId]) -> None:
        # 4: filled + cancelled + resting == qty. Only touched orders can change.
        for oid in order_ids:
            entry = self._ledger[oid]
            resting = self._book[oid].remaining if oid in self._book else 0
            assert entry.filled + entry.cancelled + resting == entry.qty, (
                f"order {oid} quantity not conserved: {entry}, resting {resting}"
            )

    def _front(self, side: Side) -> tuple[OrderId, _Resting] | None:
        # Next to match: best price, then lowest seq.
        orders = [(oid, o) for oid, o in self._book.items() if o.side is side]
        if not orders:
            return None
        sign = -1 if side is Side.BUY else 1
        return min(orders, key=lambda item: (sign * item[1].price, item[1].seq))

    def _check_stop_reason(
        self,
        side: Side,
        limit: int | None,
        stp_id: StpId | None,
        stp_policy: StpPolicy | None,
        final: Rested | Cancelled | None,
    ) -> None:
        # A remainder needs a SPEC stop reason and a matching outcome. The opposite
        # side is untouched after matching stops, so its front is where it stopped.
        front = self._front(_opposite(side))
        self_match = (
            front is not None
            and stp_id is not None
            and front[1].stp_id == stp_id
            and _marketable(side, limit, front[1].price)
        )
        if self_match:
            # (c) Only Cancel Newest stops; Cancel Oldest removes the front.
            assert stp_policy is StpPolicy.CANCEL_NEWEST, "STP should have continued"
            assert isinstance(final, Cancelled)
            assert final.purpose is CancelPurpose.SELF_TRADE_PREVENTED
            return
        # (a) opposite side empty, or (b) its front not marketable.
        assert front is None or not _marketable(side, limit, front[1].price), (
            "stopped matching early"
        )
        if limit is None:
            assert isinstance(final, Cancelled)
            assert final.purpose is CancelPurpose.UNFILLED
        else:
            assert isinstance(final, Rested)

    def observe_order(
        self,
        side: Side,
        limit: int | float | None,
        qty: int | float,
        stp_id: StpId | None,
        stp_policy: StpPolicy | None,
        events: list[Event],
    ) -> None:
        """Check a limit (limit=price) or market (limit=None) order's events."""
        if isinstance(events[0], Rejected):
            return
        # Raw inputs: anything accepted must have its exact type.
        assert type(side) is Side
        assert type(qty) is int
        assert limit is None or type(limit) is int
        assert stp_id is None or type(stp_id) is int
        assert stp_policy is None or type(stp_policy) is StpPolicy
        order_id = OrderId(events[0].seq)  # SPEC: id == seq
        opposite = _opposite(side)
        filled = 0
        final: Rested | Cancelled | None = None
        assert order_id not in self._ledger, "order id reused"
        self._ledger[order_id] = _Ledger(qty)
        touched = {order_id}

        for event in events:
            front = self._front(opposite)
            if isinstance(event, Trade):
                assert front is not None, "trade against an empty side"
                resting_id, resting = front
                assert event.resting_order_id == resting_id  # 5: FIFO
                assert event.incoming_order_id == order_id
                assert event.aggressor_side is side
                assert event.price == resting.price  # 2: resting price
                assert _marketable(side, limit, event.price)  # 1: incoming limit
                assert 0 < event.qty <= min(resting.remaining, qty - filled)
                resting.remaining -= event.qty
                filled += event.qty
                self._ledger[order_id].filled += event.qty
                self._ledger[resting_id].filled += event.qty
                touched.add(resting_id)
                if resting.remaining == 0:
                    del self._book[resting_id]
            elif isinstance(event, Cancelled) and event.order_id != order_id:
                # Only Cancel Oldest cancels mid-match: the marketable same-owner front.
                assert event.purpose is CancelPurpose.SELF_TRADE_PREVENTED
                assert stp_policy is StpPolicy.CANCEL_OLDEST
                assert front is not None and event.order_id == front[0]
                resting_id, resting = front
                assert stp_id is not None and resting.stp_id == stp_id
                assert _marketable(side, limit, resting.price)
                assert event.remaining == resting.remaining
                del self._book[resting_id]
                self._ledger[resting_id].cancelled += event.remaining
                touched.add(resting_id)
            else:
                # The incoming order's Rested/Cancelled ends the command.
                assert isinstance(event, Rested | Cancelled)
                assert event is events[-1], "terminal event must come last"
                assert event.order_id == order_id
                final = event

        if filled == qty:
            assert final is None, "fully filled order has a terminal event"
        else:
            self._check_stop_reason(side, limit, stp_id, stp_policy, final)
            assert final is not None and final.remaining == qty - filled
            if isinstance(final, Rested):
                assert limit is not None and final.price == limit
                assert final.side is side
                self._book[order_id] = _Resting(
                    side, limit, final.remaining, final.seq, stp_id
                )
            else:
                self._ledger[order_id].cancelled += final.remaining
        self._check_conservation(touched)

    def observe_cancel(self, order_id: OrderId, events: list[Event]) -> None:
        """Check a cancel's events."""
        assert len(events) == 1
        event = events[0]
        # Exact type first: True/1.0 would find order 1 in the dict.
        if type(order_id) is not int or order_id not in self._book:
            # Never existed, already filled, or already cancelled.
            assert isinstance(event, Rejected)
            return
        assert isinstance(event, Cancelled)
        assert event.order_id == order_id
        assert event.purpose is CancelPurpose.REQUESTED
        assert event.remaining == self._book.pop(order_id).remaining
        self._ledger[order_id].cancelled += event.remaining
        self._check_conservation({order_id})

    def check(self, engine: Engine) -> None:
        """Compare the rebuilt book with the engine. Call after every command."""
        for side in Side:
            totals: dict[int, int] = {}
            for o in self._book.values():
                if o.side is side:
                    totals[o.price] = totals.get(o.price, 0) + o.remaining
            assert engine.depth(side) == sorted(
                totals.items(), reverse=side is Side.BUY
            )
        bid, ask = engine.best_bid(), engine.best_ask()
        assert bid is None or ask is None or bid < ask  # 3: never crossed
        _check_structure(engine, set(self._book))


def _check_structure(engine: Engine, resting_ids: set[OrderId]) -> None:
    # 6: no empty levels or zero orders, FIFO links intact, index == book.
    # Reads private state on purpose, so the engine needs no inspection API.
    in_book: set[OrderId] = set()
    for side in Side:
        for price, level in engine._book._levels(side).items():
            assert level.head is not None, f"empty level at {price}"
            prev: OrderHandle | None = None
            node: OrderHandle | None = level.head
            while node is not None:
                order = node.order
                assert order.side is side and order.price == price
                assert order.remaining > 0
                assert not node.removed and node.prev is prev
                assert prev is None or prev.order.seq < order.seq  # FIFO
                assert engine._index.lookup(order.id) is node  # book -> index
                in_book.add(order.id)
                prev, node = node, node.next
            assert level.tail is prev
    assert in_book == resting_ids, "engine book differs from event-rebuilt book"
    assert set(engine._index._handles) == in_book  # index -> book
