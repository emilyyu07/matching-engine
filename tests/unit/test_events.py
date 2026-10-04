"""Unit tests for matching_engine.events: Trade/Rested/Cancelled/Rejected."""

from matching_engine.events import Cancelled, CancelPurpose, Rejected, Rested, Trade
from matching_engine.types import OrderId, Price, Quantity, SeqNo, Side


def test_trade_carries_resting_price_and_both_order_ids() -> None:
    trade = Trade(
        resting_order_id=OrderId(1),
        incoming_order_id=OrderId(2),
        aggressor_side=Side.BUY,
        price=Price(100),
        qty=Quantity(5),
        seq=SeqNo(2),
    )
    assert trade.price == 100
    assert trade.resting_order_id == 1
    assert trade.incoming_order_id == 2


def test_two_trades_from_the_same_command_share_seq() -> None:
    first = Trade(
        resting_order_id=OrderId(1),
        incoming_order_id=OrderId(3),
        aggressor_side=Side.BUY,
        price=Price(100),
        qty=Quantity(2),
        seq=SeqNo(3),
    )
    second = Trade(
        resting_order_id=OrderId(2),
        incoming_order_id=OrderId(3),
        aggressor_side=Side.BUY,
        price=Price(101),
        qty=Quantity(3),
        seq=SeqNo(3),
    )
    assert first.seq == second.seq == 3


def test_rested_event_equality_is_structural() -> None:
    a = Rested(
        order_id=OrderId(1),
        side=Side.BUY,
        price=Price(100),
        remaining=Quantity(5),
        seq=SeqNo(1),
    )
    b = Rested(
        order_id=OrderId(1),
        side=Side.BUY,
        price=Price(100),
        remaining=Quantity(5),
        seq=SeqNo(1),
    )
    assert a == b


def test_cancelled_requested_purpose() -> None:
    event = Cancelled(
        order_id=OrderId(1),
        remaining=Quantity(5),
        purpose=CancelPurpose.REQUESTED,
        seq=SeqNo(2),
    )
    assert event.purpose is CancelPurpose.REQUESTED


def test_cancelled_unfilled_purpose_for_market_order_remainder() -> None:
    event = Cancelled(
        order_id=OrderId(1),
        remaining=Quantity(3),
        purpose=CancelPurpose.UNFILLED,
        seq=SeqNo(1),
    )
    assert event.purpose is CancelPurpose.UNFILLED


def test_rejected_carries_seq_but_no_order_id() -> None:
    event = Rejected(seq=SeqNo(4), reason="price must be > 0, got -1")
    assert event.seq == 4
    assert not hasattr(event, "order_id")


def test_events_of_different_variants_are_never_equal() -> None:
    cancelled = Cancelled(
        order_id=OrderId(1),
        remaining=Quantity(5),
        purpose=CancelPurpose.REQUESTED,
        seq=SeqNo(2),
    )
    rejected = Rejected(seq=SeqNo(1), reason="x")
    assert cancelled != rejected


def test_trade_records_which_side_was_the_aggressor() -> None:
    trade = Trade(
        resting_order_id=OrderId(1),
        incoming_order_id=OrderId(2),
        aggressor_side=Side.SELL,
        price=Price(100),
        qty=Quantity(5),
        seq=SeqNo(2),
    )
    assert trade.aggressor_side is Side.SELL


def test_rested_records_its_side() -> None:
    rested = Rested(
        order_id=OrderId(1),
        side=Side.SELL,
        price=Price(100),
        remaining=Quantity(5),
        seq=SeqNo(1),
    )
    assert rested.side is Side.SELL


def test_cancelled_carries_the_seq_of_the_command_that_caused_it() -> None:
    event = Cancelled(
        order_id=OrderId(1),
        remaining=Quantity(5),
        purpose=CancelPurpose.REQUESTED,
        seq=SeqNo(7),
    )
    assert event.seq == 7
