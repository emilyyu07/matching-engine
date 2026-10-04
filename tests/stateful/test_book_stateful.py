"""Stateful property tests for matching_engine.book.Book.

Fuzzes random add/remove sequences against an independent Python model and
checks, after every step, that Book's best_bid/best_ask, depth(), and FIFO
ordering within a price level all agree with that model.
"""

from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, consumes, invariant, rule

from matching_engine.book import Book
from matching_engine.types import LimitOrder, OrderId, Price, Quantity, SeqNo, Side


class BookStateMachine(RuleBasedStateMachine):
    handles: Bundle[object] = Bundle("handles")

    def __init__(self) -> None:
        super().__init__()
        self.book = Book()
        self.live: list[tuple[object, LimitOrder]] = []
        self._seq = 0

    @rule(
        target=handles,
        side=st.sampled_from([Side.BUY, Side.SELL]),
        price=st.integers(min_value=1, max_value=5),
        qty=st.integers(min_value=1, max_value=5),
    )
    def add_order(self, side: Side, price: int, qty: int) -> object:
        self._seq += 1
        order = LimitOrder(
            id=OrderId(self._seq),
            side=side,
            qty=Quantity(qty),
            remaining=Quantity(qty),
            seq=SeqNo(self._seq),
            price=Price(price),
        )
        handle = self.book.add(order)
        self.live.append((handle, order))
        return handle

    @rule(handle=consumes(handles))
    def remove_order(self, handle: object) -> None:
        self.book.remove(handle)  # type: ignore[arg-type]
        self.live = [(h, o) for h, o in self.live if h is not handle]

    @invariant()
    def best_prices_match_model(self) -> None:
        buy_prices = [order.price for _, order in self.live if order.side is Side.BUY]
        sell_prices = [order.price for _, order in self.live if order.side is Side.SELL]
        assert self.book.best_bid() == (max(buy_prices) if buy_prices else None)
        assert self.book.best_ask() == (min(sell_prices) if sell_prices else None)

    @invariant()
    def depth_matches_model_and_has_no_empty_levels(self) -> None:
        for side in (Side.BUY, Side.SELL):
            totals: dict[Price, int] = {}
            for _, order in self.live:
                if order.side is side:
                    totals[order.price] = totals.get(order.price, 0) + order.remaining
            expected = sorted(totals.items(), reverse=(side is Side.BUY))
            actual = self.book.depth(side)
            assert actual == expected
            assert all(qty > 0 for _, qty in actual)

    @invariant()
    def fifo_order_within_level_matches_insertion_order(self) -> None:
        for side in (Side.BUY, Side.SELL):
            prices = {order.price for _, order in self.live if order.side is side}
            for price in prices:
                expected = [
                    order
                    for _, order in self.live
                    if order.side is side and order.price == price
                ]
                actual = list(self.book._levels(side)[price])
                assert actual == expected


TestBookStateMachine = BookStateMachine.TestCase
