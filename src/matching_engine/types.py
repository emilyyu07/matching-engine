"""Core value types: orders, sides, prices and quantities."""

from dataclasses import dataclass, field
from enum import Enum
from typing import NewType

Price = NewType("Price", int)
Quantity = NewType("Quantity", int)
OrderId = NewType("OrderId", int)
SeqNo = NewType("SeqNo", int)
StpId = NewType("StpId", int)


def make_price(raw: int) -> Price | str:
    # Exact type check: bool is an int subclass, and nothing stops a
    # runtime caller from passing a float despite the annotation.
    if type(raw) is not int:
        return f"price must be an integer, got {raw}"
    if raw <= 0:
        return f"price must be > 0, got {raw}"
    return Price(raw)


def make_quantity(raw: int) -> Quantity | str:
    if type(raw) is not int:
        return f"quantity must be an integer, got {raw}"
    if raw <= 0:
        return f"quantity must be > 0, got {raw}"
    return Quantity(raw)


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


class StpPolicy(Enum):
    CANCEL_NEWEST = "cancel_newest"
    CANCEL_OLDEST = "cancel_oldest"


@dataclass
class _OrderBase:
    id: OrderId
    side: Side
    qty: Quantity
    remaining: Quantity
    seq: SeqNo
    stp_id: StpId | None = field(default=None, kw_only=True)
    stp_policy: StpPolicy | None = field(default=None, kw_only=True)


@dataclass
class LimitOrder(_OrderBase):
    price: Price


@dataclass
class MarketOrder(_OrderBase):
    pass


Order = LimitOrder | MarketOrder
