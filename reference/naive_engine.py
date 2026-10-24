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


def _number_error(name: str, value: object) -> str | None:
    # SPEC Rejects: must be exactly an int (bool and float are not), then > 0.
    if type(value) is not int:
        return f"{name} must be an integer, got {value}"
    if value <= 0:
        return f"{name} must be > 0, got {value}"
    return None


def _stp_pair_error(stp_id: StpId | None, stp_policy: StpPolicy | None) -> str | None:
    # SPEC Rejects: stp_id and stp_policy are set together or not at all.
    if (stp_id is None) != (stp_policy is None):
        return "stp_id and stp_policy must be set together"
    return None


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
        self,
        seq: SeqNo,
        side: Side,
        limit_price: int | None,
        qty: int,
        stp_id: StpId | None,
        stp_policy: StpPolicy | None,
    ) -> tuple[list[Event], int, bool]:
        """Trade against the opposite side.

        Returns the events, what's left, and whether STP (Cancel Newest)
        stopped matching.
        """
        opposite = Side.SELL if side is Side.BUY else Side.BUY
        events: list[Event] = []
        remaining = qty
        while remaining > 0:
            front = self._front(opposite)
            if front is None or not _crosses(side, limit_price, front.price):
                break
            # SPEC: a self-match is an incoming order with STP set meeting a
            # marketable front with the same stp_id. Only the incoming
            # order's policy counts. Validation guarantees a set stp_id has
            # a policy.
            if stp_id is not None and front.stp_id == stp_id:
                if stp_policy is StpPolicy.CANCEL_NEWEST:
                    return events, remaining, True
                # CANCEL_OLDEST: cancel the resting order, retry the new front.
                self._book.remove(front)
                events.append(
                    Cancelled(
                        order_id=front.order_id,
                        remaining=Quantity(front.remaining),
                        purpose=CancelPurpose.SELF_TRADE_PREVENTED,
                        seq=seq,
                    )
                )
                continue
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
        return events, remaining, False

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
        # SPEC: checks run price -> quantity -> STP; report only the first.
        error = (
            _number_error("price", price)
            or _number_error("quantity", qty)
            or _stp_pair_error(stp_id, stp_policy)
        )
        if error is not None:
            return [Rejected(seq=seq, reason=error)]
        events, remaining, stp_stopped = self._match(
            seq, side, price, qty, stp_id, stp_policy
        )
        if stp_stopped:
            # SPEC: Cancel Newest cancels the remainder; it never rests.
            events.append(
                Cancelled(
                    order_id=OrderId(seq),
                    remaining=Quantity(remaining),
                    purpose=CancelPurpose.SELF_TRADE_PREVENTED,
                    seq=seq,
                )
            )
        elif remaining > 0:
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
        # SPEC: a market order has no price; checks run quantity -> STP.
        error = _number_error("quantity", qty) or _stp_pair_error(stp_id, stp_policy)
        if error is not None:
            return [Rejected(seq=seq, reason=error)]
        events, remaining, stp_stopped = self._match(
            seq, side, None, qty, stp_id, stp_policy
        )
        if remaining > 0:
            # SPEC: a market order never rests; its remainder is cancelled,
            # including the full quantity on an empty book. The purpose says
            # whether STP or a lack of liquidity stopped it.
            events.append(
                Cancelled(
                    order_id=OrderId(seq),
                    remaining=Quantity(remaining),
                    purpose=(
                        CancelPurpose.SELF_TRADE_PREVENTED
                        if stp_stopped
                        else CancelPurpose.UNFILLED
                    ),
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
