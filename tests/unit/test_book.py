"""Unit tests for matching_engine.book.Book: insertion, best price, depth."""

from matching_engine.book import Book, _Level
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


def test_best_bid_and_ask_empty_book() -> None:
    book = Book()
    assert book.best_bid() is None
    assert book.best_ask() is None


def test_best_bid_is_highest_price() -> None:
    book = Book()
    book.add(_limit_order(1, Side.BUY, 100, 5, 1))
    book.add(_limit_order(2, Side.BUY, 101, 3, 2))
    assert book.best_bid() == 101


def test_best_ask_is_lowest_price() -> None:
    book = Book()
    book.add(_limit_order(1, Side.SELL, 105, 5, 1))
    book.add(_limit_order(2, Side.SELL, 103, 3, 2))
    assert book.best_ask() == 103


def test_fifo_order_within_price_level() -> None:
    book = Book()
    first = _limit_order(1, Side.BUY, 100, 5, 1)
    second = _limit_order(2, Side.BUY, 100, 2, 2)
    book.add(first)
    book.add(second)
    level = book._levels(Side.BUY)[Price(100)]
    assert list(level) == [first, second]


def test_depth_bids_ordered_best_first_descending() -> None:
    book = Book()
    book.add(_limit_order(1, Side.BUY, 100, 5, 1))
    book.add(_limit_order(2, Side.BUY, 101, 3, 2))
    assert book.depth(Side.BUY) == [(101, 3), (100, 5)]


def test_depth_asks_ordered_best_first_ascending() -> None:
    book = Book()
    book.add(_limit_order(1, Side.SELL, 105, 5, 1))
    book.add(_limit_order(2, Side.SELL, 103, 3, 2))
    assert book.depth(Side.SELL) == [(103, 3), (105, 5)]


def test_depth_aggregates_quantity_at_same_price_level() -> None:
    book = Book()
    book.add(_limit_order(1, Side.BUY, 100, 5, 1))
    book.add(_limit_order(2, Side.BUY, 100, 2, 2))
    assert book.depth(Side.BUY) == [(100, 7)]


def test_level_append_to_empty_sets_head_and_tail() -> None:
    level: _Level = _Level()
    order = _limit_order(1, Side.BUY, 100, 5, 1)
    node = level.append(order)
    assert level.head is node
    assert level.tail is node
    assert node.prev is None
    assert node.next is None


def test_level_append_links_new_node_after_tail() -> None:
    level: _Level = _Level()
    first = level.append(_limit_order(1, Side.BUY, 100, 5, 1))
    second = level.append(_limit_order(2, Side.BUY, 100, 2, 2))
    assert level.head is first
    assert level.tail is second
    assert first.next is second
    assert second.prev is first


def test_level_iterates_orders_in_fifo_order() -> None:
    level: _Level = _Level()
    orders = [_limit_order(i, Side.BUY, 100, 1, i) for i in range(1, 4)]
    for order in orders:
        level.append(order)
    assert list(level) == orders


def test_level_remove_middle_node_relinks_neighbors() -> None:
    level: _Level = _Level()
    first = level.append(_limit_order(1, Side.BUY, 100, 5, 1))
    second = level.append(_limit_order(2, Side.BUY, 100, 2, 2))
    third = level.append(_limit_order(3, Side.BUY, 100, 1, 3))
    level.remove(second)
    assert list(level) == [first.order, third.order]
    assert first.next is third
    assert third.prev is first


def test_level_remove_head_updates_head_pointer() -> None:
    level: _Level = _Level()
    first = level.append(_limit_order(1, Side.BUY, 100, 5, 1))
    second = level.append(_limit_order(2, Side.BUY, 100, 2, 2))
    level.remove(first)
    assert level.head is second
    assert second.prev is None


def test_level_remove_tail_updates_tail_pointer() -> None:
    level: _Level = _Level()
    first = level.append(_limit_order(1, Side.BUY, 100, 5, 1))
    second = level.append(_limit_order(2, Side.BUY, 100, 2, 2))
    level.remove(second)
    assert level.tail is first
    assert first.next is None


def test_level_remove_sole_node_empties_level() -> None:
    level: _Level = _Level()
    only = level.append(_limit_order(1, Side.BUY, 100, 5, 1))
    level.remove(only)
    assert level.head is None
    assert level.tail is None


def test_book_remove_last_order_at_level_removes_level() -> None:
    book = Book()
    node = book.add(_limit_order(1, Side.BUY, 100, 5, 1))
    book.remove(node)
    assert book.best_bid() is None
    assert book.depth(Side.BUY) == []


def test_book_remove_middle_order_leaves_others_in_depth() -> None:
    book = Book()
    book.add(_limit_order(1, Side.BUY, 100, 5, 1))
    middle_node = book.add(_limit_order(2, Side.BUY, 100, 2, 2))
    book.add(_limit_order(3, Side.BUY, 100, 1, 3))
    book.remove(middle_node)
    assert book.depth(Side.BUY) == [(100, 6)]


def test_book_remove_best_levels_only_order_falls_back_to_next_best() -> None:
    book = Book()
    book.add(_limit_order(1, Side.BUY, 100, 5, 1))
    best_node = book.add(_limit_order(2, Side.BUY, 101, 3, 2))
    assert book.best_bid() == 101
    book.remove(best_node)
    assert book.best_bid() == 100
