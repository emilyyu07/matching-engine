"""Core value types: orders, sides, prices and quantities."""

from dataclasses import dataclass, field
from enum import Enum
from typing import NewType

Price = NewType("Price", int)
Quantity = NewType("Quantity", int)
OrderId = NewType("OrderId", int)
SeqNo = NewType("SeqNo", int)
StpId = NewType("StpId", int)


def make_price(raw: int) -> Price | RejectReason:
    # Exact type check: bool is an int subclass, and nothing stops a
    # runtime caller from passing a float despite the annotation.
    if type(raw) is not int:
        return RejectReason.PRICE_NOT_INTEGER
    if raw <= 0:
        return RejectReason.PRICE_NOT_POSITIVE
    return Price(raw)


def make_quantity(raw: int) -> Quantity | RejectReason:
    if type(raw) is not int:
        return RejectReason.QTY_NOT_INTEGER
    if raw <= 0:
        return RejectReason.QTY_NOT_POSITIVE
    return Quantity(raw)


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


class StpPolicy(Enum):
    CANCEL_NEWEST = "cancel_newest"
    CANCEL_OLDEST = "cancel_oldest"


class RejectReason(Enum):
    # One code per SPEC reject rule, so tests can tell which rule fired.
    SIDE_INVALID = "side_invalid"
    PRICE_NOT_INTEGER = "price_not_integer"
    PRICE_NOT_POSITIVE = "price_not_positive"
    QTY_NOT_INTEGER = "qty_not_integer"
    QTY_NOT_POSITIVE = "qty_not_positive"
    STP_ID_INVALID = "stp_id_invalid"
    STP_POLICY_INVALID = "stp_policy_invalid"
    STP_FIELDS_MISMATCH = "stp_fields_mismatch"
    ORDER_NOT_RESTING = "order_not_resting"


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
