"""Unit tests for matching_engine.engine: eager cancel."""

from matching_engine.book import Book
from matching_engine.engine import cancel
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


def test_cancel_removes_order_from_book_and_index() -> None:
    book = Book()
    index = OrderIndex()
    order = _limit_order(1, Side.BUY, 100, 5, 1)
    index.register(order.id, book.add(order))

    assert cancel(book, index, OrderId(1)) is True
    assert book.best_bid() is None
    assert index.lookup(OrderId(1)) is None


def test_cancel_unknown_id_returns_false_and_leaves_book_untouched() -> None:
    book = Book()
    index = OrderIndex()
    order = _limit_order(1, Side.BUY, 100, 5, 1)
    index.register(order.id, book.add(order))

    assert cancel(book, index, OrderId(99)) is False
    assert book.best_bid() == 100


def test_cancel_one_of_two_orders_at_same_level_keeps_the_other() -> None:
    book = Book()
    index = OrderIndex()
    first = _limit_order(1, Side.BUY, 100, 5, 1)
    second = _limit_order(2, Side.BUY, 100, 2, 2)
    index.register(first.id, book.add(first))
    index.register(second.id, book.add(second))

    cancel(book, index, OrderId(1))

    assert book.depth(Side.BUY) == [(100, 2)]
