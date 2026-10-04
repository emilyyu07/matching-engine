"""Event types emitted by the engine."""

from dataclasses import dataclass
from enum import Enum

from matching_engine.types import OrderId, Price, Quantity, SeqNo, Side


@dataclass(frozen=True)
class Trade:
    resting_order_id: OrderId
    incoming_order_id: OrderId
    aggressor_side: Side
    price: Price
    qty: Quantity
    seq: SeqNo


@dataclass(frozen=True)
class Rested:
    order_id: OrderId
    side: Side
    price: Price
    remaining: Quantity
    seq: SeqNo


class CancelPurpose(Enum):
    REQUESTED = "requested"
    UNFILLED = "unfilled"
    SELF_TRADE_PREVENTED = "self_trade_prevented"


@dataclass(frozen=True)
class Cancelled:
    order_id: OrderId
    remaining: Quantity
    purpose: CancelPurpose
    seq: SeqNo


@dataclass(frozen=True)
class Rejected:
    seq: SeqNo
    reason: str


Event = Trade | Rested | Cancelled | Rejected
