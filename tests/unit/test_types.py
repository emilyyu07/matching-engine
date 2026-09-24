"""Unit tests for matching_engine.types: Price and Quantity constructors."""

from hypothesis import given
from hypothesis import strategies as st

from matching_engine.types import (
    LimitOrder,
    MarketOrder,
    OrderId,
    Price,
    Quantity,
    SeqNo,
    Side,
    make_price,
    make_quantity,
)


def test_make_price_rejects_zero() -> None:
    assert isinstance(make_price(0), str)


def test_make_price_rejects_negative() -> None:
    assert isinstance(make_price(-1), str)


@given(st.integers(min_value=1))
def test_make_price_accepts_any_positive(raw: int) -> None:
    assert make_price(raw) == raw


@given(st.integers(max_value=0))
def test_make_price_rejects_non_positive(raw: int) -> None:
    assert isinstance(make_price(raw), str)


def test_make_quantity_rejects_zero() -> None:
    assert isinstance(make_quantity(0), str)


def test_make_quantity_rejects_negative() -> None:
    assert isinstance(make_quantity(-1), str)


@given(st.integers(min_value=1))
def test_make_quantity_accepts_any_positive(raw: int) -> None:
    assert make_quantity(raw) == raw


@given(st.integers(max_value=0))
def test_make_quantity_rejects_non_positive(raw: int) -> None:
    assert isinstance(make_quantity(raw), str)


def test_side_has_buy_and_sell() -> None:
    assert {Side.BUY, Side.SELL} == set(Side)


def test_limit_order_has_price_field() -> None:
    order = LimitOrder(
        id=OrderId(1),
        side=Side.BUY,
        qty=Quantity(10),
        remaining=Quantity(10),
        seq=SeqNo(1),
        price=Price(100),
    )
    assert order.price == 100


def test_market_order_has_no_price_field() -> None:
    order = MarketOrder(
        id=OrderId(1),
        side=Side.SELL,
        qty=Quantity(10),
        remaining=Quantity(10),
        seq=SeqNo(1),
    )
    assert not hasattr(order, "price")


def test_order_remaining_is_mutable_in_place() -> None:
    order = LimitOrder(
        id=OrderId(1),
        side=Side.BUY,
        qty=Quantity(10),
        remaining=Quantity(10),
        seq=SeqNo(1),
        price=Price(100),
    )
    order.remaining = Quantity(4)
    assert order.remaining == 4
