"""Matching engine: applies ordered commands and emits events."""

from matching_engine.book import Book, OrderHandle
from matching_engine.events import (
    Cancelled,
    CancelPurpose,
    Event,
    Rejected,
    Rested,
    Trade,
)
from matching_engine.order_index import OrderIndex
from matching_engine.sequencer import SeqCounter
from matching_engine.types import (
    LimitOrder,
    MarketOrder,
    OrderId,
    Price,
    Quantity,
    Side,
    StpId,
    StpPolicy,
    make_price,
    make_quantity,
)


def remove_order(
    book: Book, index: OrderIndex, order_id: OrderId
) -> OrderHandle | None:
    handle = index.lookup(order_id)
    if handle is None:
        return None
    book.remove(handle)
    index.forget(order_id)
    return handle


def _stp_error(stp_id: StpId | None, stp_policy: StpPolicy | None) -> str | None:
    if (stp_id is None) != (stp_policy is None):
        return "stp_id and stp_policy must be set together"
    return None


class Engine:
    def __init__(self) -> None:
        self._book = Book()
        self._index = OrderIndex()
        self._counter = SeqCounter()

    def best_bid(self) -> Price | None:
        return self._book.best_bid()

    def best_ask(self) -> Price | None:
        return self._book.best_ask()

    def depth(self, side: Side) -> list[tuple[Price, int]]:
        return self._book.depth(side)

    def is_resting(self, order_id: OrderId) -> bool:
        return self._index.lookup(order_id) is not None

    def submit_limit_order(
        self,
        side: Side,
        price: int,
        qty: int,
        *,
        stp_id: StpId | None = None,
        stp_policy: StpPolicy | None = None,
    ) -> list[Event]:
        seq = self._counter.advance()
        price_result = make_price(price)
        if isinstance(price_result, str):
            return [Rejected(seq=seq, reason=price_result)]
        qty_result = make_quantity(qty)
        if isinstance(qty_result, str):
            return [Rejected(seq=seq, reason=qty_result)]
        stp_error = _stp_error(stp_id, stp_policy)
        if stp_error is not None:
            return [Rejected(seq=seq, reason=stp_error)]
        order = LimitOrder(
            id=OrderId(seq),
            side=side,
            qty=qty_result,
            remaining=qty_result,
            seq=seq,
            price=price_result,
            stp_id=stp_id,
            stp_policy=stp_policy,
        )
        return self._process_new_order(order)

    def submit_market_order(
        self,
        side: Side,
        qty: int,
        *,
        stp_id: StpId | None = None,
        stp_policy: StpPolicy | None = None,
    ) -> list[Event]:
        seq = self._counter.advance()
        qty_result = make_quantity(qty)
        if isinstance(qty_result, str):
            return [Rejected(seq=seq, reason=qty_result)]
        stp_error = _stp_error(stp_id, stp_policy)
        if stp_error is not None:
            return [Rejected(seq=seq, reason=stp_error)]
        order = MarketOrder(
            id=OrderId(seq),
            side=side,
            qty=qty_result,
            remaining=qty_result,
            seq=seq,
            stp_id=stp_id,
            stp_policy=stp_policy,
        )
        return self._process_new_order(order)

    def cancel(self, order_id: OrderId) -> list[Event]:
        seq = self._counter.advance()
        handle = remove_order(self._book, self._index, order_id)
        if handle is None:
            return [Rejected(seq=seq, reason=f"order {order_id} is not resting")]
        return [
            Cancelled(
                order_id=order_id,
                remaining=handle.order.remaining,
                purpose=CancelPurpose.REQUESTED,
                seq=seq,
            )
        ]

    def _remove_resting(self, order_id: OrderId) -> None:
        # Called only for an order the loop just read from the book, so it
        # must be in the index. Explicit raise, not assert: asserts vanish
        # under `python -O`.
        if remove_order(self._book, self._index, order_id) is None:
            raise RuntimeError(f"order index out of sync with book: {order_id}")

    def _process_new_order(self, order: LimitOrder | MarketOrder) -> list[Event]:
        events: list[Event] = []
        opposite_side = Side.SELL if order.side is Side.BUY else Side.BUY
        self_trade_stopped = False

        while order.remaining > 0:
            resting_handle = self._book.front_handle(opposite_side)
            if resting_handle is None:
                break
            resting = resting_handle.order

            if isinstance(order, LimitOrder):
                marketable = (
                    resting.price <= order.price
                    if order.side is Side.BUY
                    else resting.price >= order.price
                )
                if not marketable:
                    break

            if (
                order.stp_id is not None
                and order.stp_policy is not None
                and resting.stp_id == order.stp_id
            ):
                if order.stp_policy is StpPolicy.CANCEL_NEWEST:
                    self_trade_stopped = True
                    break
                self._remove_resting(resting.id)
                events.append(
                    Cancelled(
                        order_id=resting.id,
                        remaining=resting.remaining,
                        purpose=CancelPurpose.SELF_TRADE_PREVENTED,
                        seq=order.seq,
                    )
                )
                continue

            trade_qty = Quantity(min(order.remaining, resting.remaining))
            if trade_qty <= 0:
                raise RuntimeError(
                    f"matching made no progress: resting order {resting.id} "
                    f"has remaining {resting.remaining}"
                )
            events.append(
                Trade(
                    resting_order_id=resting.id,
                    incoming_order_id=order.id,
                    aggressor_side=order.side,
                    price=resting.price,
                    qty=trade_qty,
                    seq=order.seq,
                )
            )
            order.remaining = Quantity(order.remaining - trade_qty)
            resting.remaining = Quantity(resting.remaining - trade_qty)
            if resting.remaining == 0:
                self._remove_resting(resting.id)

        if order.remaining > 0:
            if self_trade_stopped:
                events.append(
                    Cancelled(
                        order_id=order.id,
                        remaining=order.remaining,
                        purpose=CancelPurpose.SELF_TRADE_PREVENTED,
                        seq=order.seq,
                    )
                )
            elif isinstance(order, LimitOrder):
                handle = self._book.add(order)
                self._index.register(order.id, handle)
                events.append(
                    Rested(
                        order_id=order.id,
                        side=order.side,
                        price=order.price,
                        remaining=order.remaining,
                        seq=order.seq,
                    )
                )
            else:
                events.append(
                    Cancelled(
                        order_id=order.id,
                        remaining=order.remaining,
                        purpose=CancelPurpose.UNFILLED,
                        seq=order.seq,
                    )
                )

        return events
