"""Core value types: orders, sides, prices and quantities."""

from dataclasses import dataclass
from enum import Enum
from typing import NewType

Price = NewType("Price", int)
Quantity = NewType("Quantity", int)
OrderId = NewType("OrderId", int)
SeqNo = NewType("SeqNo", int)


def make_price(raw: int) -> Price | str:
    if raw <= 0:
        return f"price must be > 0, got {raw}"
    return Price(raw)


def make_quantity(raw: int) -> Quantity | str:
    if raw <= 0:
        return f"quantity must be > 0, got {raw}"
    return Quantity(raw)


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class _OrderBase:
    id: OrderId
    side: Side
    qty: Quantity
    remaining: Quantity
    seq: SeqNo


@dataclass
class LimitOrder(_OrderBase):
    price: Price


@dataclass
class MarketOrder(_OrderBase):
    pass


Order = LimitOrder | MarketOrder
