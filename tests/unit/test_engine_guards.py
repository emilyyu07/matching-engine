"""White-box tests for the matching loop's internal-invariant guards.

These deliberately corrupt Engine's private state, which correct code can
never do, to prove a broken invariant fails loudly instead of hanging or
silently continuing.
"""

import pytest

from matching_engine.engine import Engine
from matching_engine.types import LimitOrder, OrderId, Price, Quantity, SeqNo, Side


def _resting_sell(remaining: int) -> LimitOrder:
    return LimitOrder(
        id=OrderId(100),
        side=Side.SELL,
        qty=Quantity(5),
        remaining=Quantity(remaining),
        seq=SeqNo(100),
        price=Price(100),
    )


def test_zero_quantity_resting_order_raises_instead_of_looping_forever() -> None:
    engine = Engine()
    order = _resting_sell(0)
    engine._index.register(order.id, engine._book.add(order))
    with pytest.raises(RuntimeError, match="no progress"):
        engine.submit_limit_order(Side.BUY, 100, 5)


def test_resting_order_missing_from_index_raises_on_fill() -> None:
    engine = Engine()
    engine._book.add(_resting_sell(5))
    with pytest.raises(RuntimeError, match="out of sync"):
        engine.submit_limit_order(Side.BUY, 100, 5)
