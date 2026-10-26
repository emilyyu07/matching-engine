"""Naive engine written from SPEC.md only, for differential tests.

One flat list, re-scanned on every query. Shares data shapes with the real
engine, never logic (D-13).
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
    RejectReason,
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


def _number_error(
    value: object, not_integer: RejectReason, not_positive: RejectReason
) -> RejectReason | None:
    # SPEC Rejects: exactly an int (not bool or float), then > 0.
    if type(value) is not int:
        return not_integer
    if value <= 0:
        return not_positive
    return None


def _side_error(side: object) -> RejectReason | None:
    # SPEC Rejects: side must be exactly a Side.
    if type(side) is not Side:
        return RejectReason.SIDE_INVALID
    return None


def _stp_pair_error(
    stp_id: StpId | None, stp_policy: StpPolicy | None
) -> RejectReason | None:
    # SPEC Rejects: each field's type, then both set or both unset.
    if stp_id is not None and type(stp_id) is not int:
        return RejectReason.STP_ID_INVALID
    if stp_policy is not None and type(stp_policy) is not StpPolicy:
        return RejectReason.STP_POLICY_INVALID
    if (stp_id is None) != (stp_policy is None):
        return RejectReason.STP_FIELDS_MISMATCH
    return None


def _crosses(side: Side, limit_price: int | None, resting_price: int) -> bool:
    # SPEC: market orders always cross; a limit BUY needs resting <= limit, a SELL >=.
    if limit_price is None:
        return True
    if side is Side.BUY:
        return resting_price <= limit_price
    return resting_price >= limit_price


class NaiveEngine:
    def __init__(self) -> None:
        self._last_seq = 0
        # Both sides, in arrival (seq) order.
        self._book: list[_Resting] = []

    def _next_seq(self) -> SeqNo:
        # SPEC: every command consumes one seq, before validation.
        self._last_seq += 1
        return SeqNo(self._last_seq)

    def _front(self, side: Side) -> _Resting | None:
        orders = [o for o in self._book if o.side is side]
        if not orders:
            return None
        # SPEC: best price, then lowest seq (OrderId == SeqNo).
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
        """Match against the opposite side: (events, remaining, stopped by STP)."""
        opposite = Side.SELL if side is Side.BUY else Side.BUY
        events: list[Event] = []
        remaining = qty
        while remaining > 0:
            front = self._front(opposite)
            if front is None or not _crosses(side, limit_price, front.price):
                break
            # SPEC: self-match = marketable front with the incoming stp_id; only
            # the incoming policy counts. Validation pairs stp_id with a policy.
            if stp_id is not None and front.stp_id == stp_id:
                if stp_policy is StpPolicy.CANCEL_NEWEST:
                    return events, remaining, True
                # Cancel Oldest: cancel the resting order, retry the new front.
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
            # In place, so a partial fill keeps its queue position.
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
        # SPEC: check side -> price -> quantity -> STP; report the first failure.
        error = (
            _side_error(side)
            or _number_error(
                price,
                RejectReason.PRICE_NOT_INTEGER,
                RejectReason.PRICE_NOT_POSITIVE,
            )
            or _number_error(
                qty, RejectReason.QTY_NOT_INTEGER, RejectReason.QTY_NOT_POSITIVE
            )
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
        # SPEC: no price to check; side -> quantity -> STP.
        error = (
            _side_error(side)
            or _number_error(
                qty, RejectReason.QTY_NOT_INTEGER, RejectReason.QTY_NOT_POSITIVE
            )
            or _stp_pair_error(stp_id, stp_policy)
        )
        if error is not None:
            return [Rejected(seq=seq, reason=error)]
        events, remaining, stp_stopped = self._match(
            seq, side, None, qty, stp_id, stp_policy
        )
        if remaining > 0:
            # SPEC: a market order never rests; the remainder is cancelled, and the
            # purpose says whether STP or lack of liquidity stopped it.
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
        seq = self._next_seq()  # SPEC: rejected cancels consume a seq too
        for order in self._book:
            # SPEC: id must be exactly an int; True == 1 must not match order 1.
            if type(order_id) is int and order.order_id == order_id:
                self._book.remove(order)
                return [
                    Cancelled(
                        order_id=order_id,
                        remaining=Quantity(order.remaining),  # after partial fills
                        purpose=CancelPurpose.REQUESTED,
                        seq=seq,
                    )
                ]
        return [Rejected(seq=seq, reason=RejectReason.ORDER_NOT_RESTING)]

    def depth(self, side: Side) -> list[tuple[int, int]]:
        totals: dict[int, int] = {}
        for o in self._book:
            if o.side is side:
                totals[o.price] = totals.get(o.price, 0) + o.remaining
        # Best first: bids descending, asks ascending.
        return sorted(totals.items(), reverse=side is Side.BUY)
