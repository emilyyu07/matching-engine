"""Maps OrderId to the OrderHandle needed to act on a resting order."""

from matching_engine.book import OrderHandle
from matching_engine.types import OrderId


class OrderIndex:
    def __init__(self) -> None:
        self._handles: dict[OrderId, OrderHandle] = {}

    def register(self, order_id: OrderId, handle: OrderHandle) -> None:
        self._handles[order_id] = handle

    def lookup(self, order_id: OrderId) -> OrderHandle | None:
        return self._handles.get(order_id)

    def forget(self, order_id: OrderId) -> None:
        del self._handles[order_id]
