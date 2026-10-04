"""Matching engine: applies ordered commands and emits events."""

from matching_engine.book import Book
from matching_engine.order_index import OrderIndex
from matching_engine.types import OrderId


def cancel(book: Book, index: OrderIndex, order_id: OrderId) -> bool:
    handle = index.lookup(order_id)
    if handle is None:
        return False
    book.remove(handle)
    index.forget(order_id)
    return True
