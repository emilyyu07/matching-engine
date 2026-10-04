"""Unit tests for matching_engine.engine.Engine: the matching loop."""

from matching_engine.engine import Engine
from matching_engine.events import Cancelled, CancelPurpose, Rejected, Rested, Trade
from matching_engine.types import OrderId, Side, StpId, StpPolicy


def test_resting_limit_order_with_no_match_produces_rested() -> None:
    engine = Engine()
    events = engine.submit_limit_order(Side.BUY, 100, 5)
    assert events == [
        Rested(order_id=OrderId(1), side=Side.BUY, price=100, remaining=5, seq=1)
    ]


def test_marketable_limit_order_fully_fills_against_single_resting_order() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5)
    events = engine.submit_limit_order(Side.BUY, 100, 5)
    assert events == [
        Trade(
            resting_order_id=OrderId(1),
            incoming_order_id=OrderId(2),
            aggressor_side=Side.BUY,
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
            aggressor_side=Side.BUY,
            price=100,
            qty=3,
            seq=2,
        ),
        Rested(order_id=OrderId(2), side=Side.BUY, price=100, remaining=2, seq=2),
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
            aggressor_side=Side.BUY,
            price=100,
            qty=2,
            seq=3,
        ),
        Trade(
            resting_order_id=OrderId(2),
            incoming_order_id=OrderId(3),
            aggressor_side=Side.BUY,
            price=101,
            qty=3,
            seq=3,
        ),
    ]


def test_sell_aggressor_is_recorded_on_the_trade() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 100, 5)
    events = engine.submit_limit_order(Side.SELL, 100, 5)
    trade = events[0]
    assert isinstance(trade, Trade)
    assert trade.aggressor_side is Side.SELL


def test_non_marketable_limit_order_does_not_cross() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5)
    events = engine.submit_limit_order(Side.BUY, 99, 5)
    assert events == [
        Rested(order_id=OrderId(2), side=Side.BUY, price=99, remaining=5, seq=2)
    ]


def test_partially_filled_resting_order_keeps_its_queue_position() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 100, 5)  # A, id 1
    engine.submit_limit_order(Side.BUY, 100, 5)  # B, id 2
    engine.submit_limit_order(Side.SELL, 100, 2)  # partially fills A
    events = engine.submit_limit_order(Side.SELL, 100, 4)
    trades = [e for e in events if isinstance(e, Trade)]
    assert [(t.resting_order_id, t.qty) for t in trades] == [
        (OrderId(1), 3),
        (OrderId(2), 1),
    ]


def test_market_order_fully_fills_against_resting_liquidity() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5)
    events = engine.submit_market_order(Side.BUY, 5)
    assert events == [
        Trade(
            resting_order_id=OrderId(1),
            incoming_order_id=OrderId(2),
            aggressor_side=Side.BUY,
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
            aggressor_side=Side.BUY,
            price=100,
            qty=3,
            seq=2,
        ),
        Cancelled(
            order_id=OrderId(2),
            remaining=2,
            purpose=CancelPurpose.UNFILLED,
            seq=2,
        ),
    ]


def test_market_order_on_empty_book_cancels_full_quantity_unfilled() -> None:
    engine = Engine()
    events = engine.submit_market_order(Side.BUY, 5)
    assert events == [
        Cancelled(
            order_id=OrderId(1),
            remaining=5,
            purpose=CancelPurpose.UNFILLED,
            seq=1,
        )
    ]


def test_invalid_price_is_rejected_and_never_touches_the_book() -> None:
    engine = Engine()
    events = engine.submit_limit_order(Side.BUY, 0, 5)
    assert events == [Rejected(seq=1, reason="price must be > 0, got 0")]
    assert engine.best_bid() is None


def test_invalid_quantity_is_rejected() -> None:
    engine = Engine()
    events = engine.submit_limit_order(Side.BUY, 100, -1)
    assert events == [Rejected(seq=1, reason="quantity must be > 0, got -1")]


def test_cancel_emits_cancelled_requested_with_its_own_seq() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 100, 5)
    events = engine.cancel(OrderId(1))
    assert events == [
        Cancelled(
            order_id=OrderId(1),
            remaining=5,
            purpose=CancelPurpose.REQUESTED,
            seq=2,
        )
    ]
    assert engine.best_bid() is None
    assert not engine.is_resting(OrderId(1))


def test_cancel_of_partially_filled_order_reports_only_what_was_left() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 100, 5)
    engine.submit_limit_order(Side.SELL, 100, 2)
    events = engine.cancel(OrderId(1))
    assert events == [
        Cancelled(
            order_id=OrderId(1),
            remaining=3,
            purpose=CancelPurpose.REQUESTED,
            seq=3,
        )
    ]


def test_cancel_of_unknown_id_is_rejected_with_a_seq() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 100, 5)
    events = engine.cancel(OrderId(99))
    assert events == [Rejected(seq=2, reason="order 99 is not resting")]
    assert engine.best_bid() == 100


def test_cancel_consumes_a_seq_so_the_next_order_id_skips_it() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 100, 5)
    engine.cancel(OrderId(1))
    events = engine.submit_limit_order(Side.BUY, 100, 5)
    assert events == [
        Rested(order_id=OrderId(3), side=Side.BUY, price=100, remaining=5, seq=3)
    ]


def test_cancel_one_of_two_orders_at_same_level_keeps_the_other() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 100, 5)
    engine.submit_limit_order(Side.BUY, 100, 2)
    engine.cancel(OrderId(1))
    assert engine.depth(Side.BUY) == [(100, 2)]


def test_full_fill_forgets_the_order_so_a_later_cancel_is_rejected() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 5)
    engine.submit_limit_order(Side.BUY, 100, 5)
    assert not engine.is_resting(OrderId(1))
    events = engine.cancel(OrderId(1))
    assert events == [Rejected(seq=3, reason="order 1 is not resting")]


def test_read_only_queries_reflect_both_sides() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 99, 5)
    engine.submit_limit_order(Side.BUY, 98, 1)
    engine.submit_limit_order(Side.SELL, 101, 3)
    assert engine.best_bid() == 99
    assert engine.best_ask() == 101
    assert engine.depth(Side.BUY) == [(99, 5), (98, 1)]
    assert engine.depth(Side.SELL) == [(101, 3)]
    assert engine.is_resting(OrderId(3))


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
            order_id=OrderId(2),
            remaining=5,
            purpose=CancelPurpose.SELF_TRADE_PREVENTED,
            seq=2,
        )
    ]
    assert engine.best_ask() == 100


def test_cancel_newest_after_partial_fill_cancels_only_the_remainder() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 2)  # other owner
    engine.submit_limit_order(Side.SELL, 100, 5, stp_id=StpId(1))
    events = engine.submit_limit_order(
        Side.BUY,
        100,
        5,
        stp_id=StpId(1),
        stp_policy=StpPolicy.CANCEL_NEWEST,
    )
    assert events == [
        Trade(
            resting_order_id=OrderId(1),
            incoming_order_id=OrderId(3),
            aggressor_side=Side.BUY,
            price=100,
            qty=2,
            seq=3,
        ),
        Cancelled(
            order_id=OrderId(3),
            remaining=3,
            purpose=CancelPurpose.SELF_TRADE_PREVENTED,
            seq=3,
        ),
    ]
    assert engine.best_bid() is None
    assert engine.depth(Side.SELL) == [(100, 5)]


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
            order_id=OrderId(1),
            remaining=5,
            purpose=CancelPurpose.SELF_TRADE_PREVENTED,
            seq=3,
        ),
        Trade(
            resting_order_id=OrderId(2),
            incoming_order_id=OrderId(3),
            aggressor_side=Side.BUY,
            price=100,
            qty=3,
            seq=3,
        ),
        Rested(order_id=OrderId(3), side=Side.BUY, price=100, remaining=2, seq=3),
    ]


def test_cancel_oldest_removes_several_consecutive_self_orders() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.SELL, 100, 1, stp_id=StpId(1))
    engine.submit_limit_order(Side.SELL, 100, 1, stp_id=StpId(1))
    engine.submit_limit_order(Side.SELL, 101, 4)
    events = engine.submit_limit_order(
        Side.BUY,
        101,
        4,
        stp_id=StpId(1),
        stp_policy=StpPolicy.CANCEL_OLDEST,
    )
    assert [type(e).__name__ for e in events] == ["Cancelled", "Cancelled", "Trade"]
    assert engine.best_ask() is None


def test_cancel_oldest_works_for_market_orders() -> None:
    engine = Engine()
    engine.submit_limit_order(Side.BUY, 100, 5, stp_id=StpId(1))
    events = engine.submit_market_order(
        Side.SELL, 3, stp_id=StpId(1), stp_policy=StpPolicy.CANCEL_OLDEST
    )
    assert events == [
        Cancelled(
            order_id=OrderId(1),
            remaining=5,
            purpose=CancelPurpose.SELF_TRADE_PREVENTED,
            seq=2,
        ),
        Cancelled(
            order_id=OrderId(2),
            remaining=3,
            purpose=CancelPurpose.UNFILLED,
            seq=2,
        ),
    ]
