"""Unit tests for matching_engine.order_index.OrderIndex."""

import pytest

from matching_engine.book import OrderHandle
from matching_engine.order_index import OrderIndex
from matching_engine.types import LimitOrder, OrderId, Price, Quantity, SeqNo, Side


def _handle(order_id: int) -> OrderHandle:
    order = LimitOrder(
        id=OrderId(order_id),
        side=Side.BUY,
        qty=Quantity(5),
        remaining=Quantity(5),
        seq=SeqNo(order_id),
        price=Price(100),
    )
    return OrderHandle(order=order)


def test_lookup_missing_id_returns_none() -> None:
    index = OrderIndex()
    assert index.lookup(OrderId(1)) is None


def test_register_then_lookup_returns_same_handle() -> None:
    index = OrderIndex()
    handle = _handle(1)
    index.register(OrderId(1), handle)
    assert index.lookup(OrderId(1)) is handle


def test_forget_removes_entry() -> None:
    index = OrderIndex()
    handle = _handle(1)
    index.register(OrderId(1), handle)
    index.forget(OrderId(1))
    assert index.lookup(OrderId(1)) is None


def test_forget_missing_id_raises_key_error() -> None:
    index = OrderIndex()
    with pytest.raises(KeyError):
        index.forget(OrderId(1))
