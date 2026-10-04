"""Unit tests for matching_engine.engine.remove_order: the atomic helper."""

from matching_engine.book import Book
from matching_engine.engine import remove_order
from matching_engine.order_index import OrderIndex
from matching_engine.types import LimitOrder, OrderId, Price, Quantity, SeqNo, Side


def _limit_order(
    order_id: int, side: Side, price: int, qty: int, seq: int
) -> LimitOrder:
    return LimitOrder(
        id=OrderId(order_id),
        side=side,
        qty=Quantity(qty),
        remaining=Quantity(qty),
        seq=SeqNo(seq),
        price=Price(price),
    )


def test_remove_order_returns_handle_and_clears_both_book_and_index() -> None:
    book = Book()
    index = OrderIndex()
    order = _limit_order(1, Side.BUY, 100, 5, 1)
    index.register(order.id, book.add(order))

    handle = remove_order(book, index, OrderId(1))

    assert handle is not None
    assert handle.order.id == 1
    assert book.best_bid() is None
    assert index.lookup(OrderId(1)) is None


def test_remove_order_unknown_id_returns_none_and_touches_nothing() -> None:
    book = Book()
    index = OrderIndex()
    order = _limit_order(1, Side.BUY, 100, 5, 1)
    index.register(order.id, book.add(order))

    assert remove_order(book, index, OrderId(99)) is None
    assert book.best_bid() == 100
    assert index.lookup(OrderId(1)) is not None
