"""Order book storage: price levels, best bid/ask, depth snapshot."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sortedcontainers import SortedDict

from matching_engine.types import LimitOrder, Price, Side


@dataclass(eq=False, repr=False)
class OrderHandle:
    order: LimitOrder
    prev: OrderHandle | None = None
    next: OrderHandle | None = None
    removed: bool = False


@dataclass
class _Level:
    head: OrderHandle | None = None
    tail: OrderHandle | None = None

    def append(self, order: LimitOrder) -> OrderHandle:
        node = OrderHandle(order=order, prev=self.tail)
        if self.tail is None:
            self.head = node
        else:
            self.tail.next = node
        self.tail = node
        return node

    def remove(self, node: OrderHandle) -> None:
        if node.removed:
            raise ValueError("order already removed from its price level")
        node.removed = True
        if node.prev is None:
            self.head = node.next
        else:
            node.prev.next = node.next
        if node.next is None:
            self.tail = node.prev
        else:
            node.next.prev = node.prev

    def __iter__(self) -> Iterator[LimitOrder]:
        node = self.head
        while node is not None:
            yield node.order
            node = node.next


class Book:
    def __init__(self) -> None:
        self._bids: SortedDict[Price, _Level] = SortedDict()
        self._asks: SortedDict[Price, _Level] = SortedDict()

    def _levels(self, side: Side) -> SortedDict[Price, _Level]:
        return self._bids if side is Side.BUY else self._asks

    def add(self, order: LimitOrder) -> OrderHandle:
        levels = self._levels(order.side)
        return levels.setdefault(order.price, _Level()).append(order)

    def front_handle(self, side: Side) -> OrderHandle | None:
        levels = self._levels(side)
        if not levels:
            return None
        _, level = levels.peekitem(-1) if side is Side.BUY else levels.peekitem(0)
        return level.head

    def remove(self, node: OrderHandle) -> None:
        if node.removed:
            raise ValueError("order already removed from its price level")
        order = node.order
        levels = self._levels(order.side)
        level = levels[order.price]
        level.remove(node)
        if level.head is None:
            del levels[order.price]

    def best_bid(self) -> Price | None:
        if not self._bids:
            return None
        return self._bids.peekitem(-1)[0]

    def best_ask(self) -> Price | None:
        if not self._asks:
            return None
        return self._asks.peekitem(0)[0]

    def depth(self, side: Side) -> list[tuple[Price, int]]:
        levels = self._levels(side)
        ordered = reversed(levels.items()) if side is Side.BUY else levels.items()
        return [
            (price, sum(order.remaining for order in level)) for price, level in ordered
        ]
