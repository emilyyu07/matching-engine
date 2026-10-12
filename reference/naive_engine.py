"""Naive matching engine written from SPEC.md only, for differential tests.

Deliberately simple over fast: one flat list of resting orders, re-scanned
on every query. Shares only data shapes with the real engine (D-13), never
logic.
"""

from dataclasses import dataclass

from matching_engine.events import (
    Cancelled,
    CancelPurpose,
    Event,
    Rejected,
    Rested,
    Trade,
)
from matching_engine.types import (
    OrderId,
    Price,
    Quantity,
    SeqNo,
    Side,
    StpId,
    StpPolicy,
)


@dataclass
class _Resting:
    order_id: OrderId  # SPEC: equals the seq it arrived with
    side: Side
    price: int
    remaining: int
    stp_id: StpId | None


def _crosses(side: Side, limit_price: int | None, resting_price: int) -> bool:
    # SPEC: a market order (no limit price) is always marketable. A limit
    # BUY crosses resting.price <= order.price; a SELL, >=. Equal matches.
    if limit_price is None:
        return True
    if side is Side.BUY:
        return resting_price <= limit_price
    return resting_price >= limit_price


class NaiveEngine:
    def __init__(self) -> None:
        self._last_seq = 0
        # Both sides, appended in arrival (seq) order.
        self._book: list[_Resting] = []

    def _next_seq(self) -> SeqNo:
        # SPEC: every command consumes one seq, assigned before validation.
        self._last_seq += 1
        return SeqNo(self._last_seq)

    def _front(self, side: Side) -> _Resting | None:
        orders = [o for o in self._book if o.side is side]
        if not orders:
            return None
        # SPEC: best price first (highest bid / lowest ask), then lowest
        # SeqNo. Relies on OrderId == SeqNo.
        if side is Side.BUY:
            return min(orders, key=lambda o: (-o.price, o.order_id))
        return min(orders, key=lambda o: (o.price, o.order_id))

    def _match(
        self, seq: SeqNo, side: Side, limit_price: int | None, qty: int
    ) -> tuple[list[Event], int]:
        """Trade against the opposite side; return the trades and what's left."""
        opposite = Side.SELL if side is Side.BUY else Side.BUY
        events: list[Event] = []
        remaining = qty
        while remaining > 0:
            front = self._front(opposite)
            if front is None or not _crosses(side, limit_price, front.price):
                break
            fill = min(remaining, front.remaining)
            events.append(
                Trade(
                    resting_order_id=front.order_id,
                    incoming_order_id=OrderId(seq),
                    aggressor_side=side,
                    price=Price(front.price),  # SPEC: the resting order's price
                    qty=Quantity(fill),
                    seq=seq,
                )
            )
            remaining -= fill
            # In place, so a partially filled order keeps its queue position.
            front.remaining -= fill
            if front.remaining == 0:
                self._book.remove(front)
        return events, remaining

    def submit_limit_order(
        self,
        side: Side,
        price: int,
        qty: int,
        *,
        stp_id: StpId | None = None,
        stp_policy: StpPolicy | None = None,
    ) -> list[Event]:
        seq = self._next_seq()
        events, remaining = self._match(seq, side, price, qty)
        if remaining > 0:
            # SPEC: the remainder rests at its own price, at the back.
            self._book.append(_Resting(OrderId(seq), side, price, remaining, stp_id))
            events.append(
                Rested(
                    order_id=OrderId(seq),
                    side=side,
                    price=Price(price),
                    remaining=Quantity(remaining),
                    seq=seq,
                )
            )
        return events

    def submit_market_order(
        self,
        side: Side,
        qty: int,
        *,
        stp_id: StpId | None = None,
        stp_policy: StpPolicy | None = None,
    ) -> list[Event]:
        seq = self._next_seq()
        events, remaining = self._match(seq, side, None, qty)
        if remaining > 0:
            # SPEC: a market order never rests; its remainder is cancelled,
            # including the full quantity on an empty book.
            events.append(
                Cancelled(
                    order_id=OrderId(seq),
                    remaining=Quantity(remaining),
                    purpose=CancelPurpose.UNFILLED,
                    seq=seq,
                )
            )
        return events

    def cancel(self, order_id: OrderId) -> list[Event]:
        seq = self._next_seq()  # SPEC: a rejected cancel consumes a seq too
        for order in self._book:
            if order.order_id == order_id:
                self._book.remove(order)
                return [
                    Cancelled(
                        order_id=order_id,
                        remaining=Quantity(order.remaining),  # after partial fills
                        purpose=CancelPurpose.REQUESTED,
                        seq=seq,
                    )
                ]
        return [Rejected(seq=seq, reason=f"order {order_id} is not resting")]

    def depth(self, side: Side) -> list[tuple[int, int]]:
        totals: dict[int, int] = {}
        for o in self._book:
            if o.side is side:
                totals[o.price] = totals.get(o.price, 0) + o.remaining
        # Best first: bids descending, asks ascending.
        return sorted(totals.items(), reverse=side is Side.BUY)
