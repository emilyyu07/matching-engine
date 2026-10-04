"""Unit tests for matching_engine.engine.Engine: the matching loop."""

from matching_engine.engine import Engine
from matching_engine.events import Cancelled, CancelPurpose, Rejected, Rested, Trade
from matching_engine.types import OrderId, Side, StpId, StpPolicy


def test_resting_limit_order_with_no_match_produces_rested() -> None:
    engine = Engine()
    events = engine.submit_limit_order(Side.BUY, 100, 5)
    assert events == [Rested(order_id=OrderId(1), price=100, remaining=5, seq=1)]


def test_marketable_limit_order_fully_fills_against_single_resting_order() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5)
    events = engine.submit_limit_order(Side.BUY, 100, 5)
    assert events == [
        Trade(
            resting_order_id=OrderId(1),
            incoming_order_id=OrderId(2),
            price=100,
            qty=5,
            seq=2,
        )
    ]


def test_trade_prices_at_the_resting_orders_price_not_the_aggressors() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5)
    events = engine.submit_limit_order(Side.BUY, 105, 5)
    assert len(events) == 1
    trade = events[0]
    assert isinstance(trade, Trade)
    assert trade.price == 100


def test_partial_fill_rests_the_remainder() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 3)
    events = engine.submit_limit_order(Side.BUY, 100, 5)
    assert events == [
        Trade(
            resting_order_id=OrderId(1),
            incoming_order_id=OrderId(2),
            price=100,
            qty=3,
            seq=2,
        ),
        Rested(order_id=OrderId(2), price=100, remaining=2, seq=2),
    ]


def test_marketable_order_walks_multiple_price_levels() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 2)
    engine.submit_limit_order(Side.SELL, 101, 3)
    events = engine.submit_limit_order(Side.BUY, 101, 5)
    assert events == [
        Trade(
            resting_order_id=OrderId(1),
            incoming_order_id=OrderId(3),
            price=100,
            qty=2,
            seq=3,
        ),
        Trade(
            resting_order_id=OrderId(2),
            incoming_order_id=OrderId(3),
            price=101,
            qty=3,
            seq=3,
        ),
    ]


def test_non_marketable_limit_order_does_not_cross() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5)
    events = engine.submit_limit_order(Side.BUY, 99, 5)
    assert events == [Rested(order_id=OrderId(2), price=99, remaining=5, seq=2)]


def test_market_order_fully_fills_against_resting_liquidity() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5)
    events = engine.submit_market_order(Side.BUY, 5)
    assert events == [
        Trade(
            resting_order_id=OrderId(1),
            incoming_order_id=OrderId(2),
            price=100,
            qty=5,
            seq=2,
        )
    ]


def test_market_order_with_insufficient_liquidity_cancels_remainder_unfilled() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 3)
    events = engine.submit_market_order(Side.BUY, 5)
    assert events == [
        Trade(
            resting_order_id=OrderId(1),
            incoming_order_id=OrderId(2),
            price=100,
            qty=3,
            seq=2,
        ),
        Cancelled(order_id=OrderId(2), remaining=2, purpose=CancelPurpose.UNFILLED),
    ]


def test_market_order_on_empty_book_cancels_full_quantity_unfilled() -> None:
    engine = Engine()
    events = engine.submit_market_order(Side.BUY, 5)
    assert events == [
        Cancelled(order_id=OrderId(1), remaining=5, purpose=CancelPurpose.UNFILLED)
    ]


def test_invalid_price_is_rejected_and_never_touches_the_book() -> None:
    engine = Engine()
    events = engine.submit_limit_order(Side.BUY, 0, 5)
    assert events == [Rejected(seq=1, reason="price must be > 0, got 0")]
    assert engine.book.best_bid() is None


def test_invalid_quantity_is_rejected() -> None:
    engine = Engine()
    events = engine.submit_limit_order(Side.BUY, 100, -1)
    assert events == [Rejected(seq=1, reason="quantity must be > 0, got -1")]


def test_engine_cancel_removes_resting_order() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 100, 5)
    assert engine.cancel(OrderId(1)) is True
    assert engine.book.best_bid() is None


def test_full_fill_forgets_the_order_from_the_index_too() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5)
    engine.submit_limit_order(Side.BUY, 100, 5)
    assert engine.index.lookup(OrderId(1)) is None
    assert engine.cancel(OrderId(1)) is False


def test_self_trade_prevention_cancel_newest_stops_matching_and_does_not_rest() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5, stp_id=StpId(1))
    events = engine.submit_limit_order(
        Side.BUY,
        100,
        5,
        stp_id=StpId(1),
        stp_policy=StpPolicy.CANCEL_NEWEST,
    )
    assert events == [
        Cancelled(
            order_id=OrderId(2), remaining=5, purpose=CancelPurpose.SELF_TRADE_PREVENTED
        )
    ]
    assert engine.book.best_ask() == 100


def test_self_trade_prevention_cancel_oldest_removes_resting_and_continues() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5, stp_id=StpId(1))
    engine.submit_limit_order(Side.SELL, 100, 3)
    events = engine.submit_limit_order(
        Side.BUY,
        100,
        5,
        stp_id=StpId(1),
        stp_policy=StpPolicy.CANCEL_OLDEST,
    )
    assert events == [
        Cancelled(
            order_id=OrderId(1), remaining=5, purpose=CancelPurpose.SELF_TRADE_PREVENTED
        ),
        Trade(
            resting_order_id=OrderId(2),
            incoming_order_id=OrderId(3),
            price=100,
            qty=3,
            seq=3,
        ),
        Rested(order_id=OrderId(3), price=100, remaining=2, seq=3),
    ]
