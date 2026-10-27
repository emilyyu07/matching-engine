"""The mutant catalogue: one known bug per entry, grouped by the code it breaks."""

from mutation.mutants import Mutant

_ENGINE = "engine.py"
_BOOK = "book.py"
_TYPES = "types.py"

MUTANTS: tuple[Mutant, ...] = (
    # Matching and trade price
    Mutant(
        "buy-cross-strict",
        _ENGINE,
        "resting.price <= order.price",
        "resting.price < order.price",
        "a buy at the ask price must trade (marketability, inv. 1/3)",
    ),
    Mutant(
        "sell-cross-strict",
        _ENGINE,
        "resting.price >= order.price",
        "resting.price > order.price",
        "a sell at the bid price must trade (marketability, inv. 1/3)",
    ),
    Mutant(
        "trade-at-incoming-price",
        _ENGINE,
        "                    price=resting.price,\n                    qty=trade_qty,",
        "                    price=(\n"
        "                        order.price\n"
        "                        if isinstance(order, LimitOrder)\n"
        "                        else resting.price\n"
        "                    ),\n"
        "                    qty=trade_qty,",
        "trade price is the resting order's price (inv. 2)",
    ),
    # Priority and book structure
    Mutant(
        "partial-fill-requeues",
        _ENGINE,
        "            if resting.remaining == 0:\n"
        "                self._remove_resting(resting.id)",
        "            self._remove_resting(resting.id)\n"
        "            if resting.remaining > 0:\n"
        "                handle = self._book.add(resting)\n"
        "                self._index.register(resting.id, handle)",
        "a partly filled resting order keeps its queue position (D-11, inv. 5)",
    ),
    Mutant(
        "level-lifo",
        _BOOK,
        "return level.head",
        "return level.tail",
        "FIFO within a price level (inv. 5)",
    ),
    Mutant(
        "wrong-end-of-book",
        _BOOK,
        "levels.peekitem(-1) if side is Side.BUY else levels.peekitem(0)",
        "levels.peekitem(0)",
        "best price first: highest bid matches before lower bids",
    ),
    Mutant(
        "empty-level-kept",
        _BOOK,
        "        if level.head is None:\n            del levels[order.price]",
        "        if level.head is None:\n            pass",
        "no empty price levels (inv. 6)",
    ),
    Mutant(
        "depth-ignores-remaining",
        _BOOK,
        "sum(order.remaining for order in level)",
        "sum(order.qty for order in level)",
        "depth reports remaining, not original, quantity",
    ),
    # Cancel
    Mutant(
        "cancel-leaves-in-book",
        _ENGINE,
        "            remove_order(self._book, self._index, order_id)\n"
        "            if type(order_id) is int",
        "            self._index.lookup(order_id)\n"
        "            if type(order_id) is int",
        "a cancelled order leaves book and index (inv. 6)",
    ),
    Mutant(
        "cancel-wrong-remaining",
        _ENGINE,
        "remaining=handle.order.remaining,",
        "remaining=handle.order.qty,",
        "Cancelled reports the unfilled quantity (conservation, inv. 4)",
    ),
    Mutant(
        "cancel-reuses-seq",
        _ENGINE,
        "        seq = self._counter.advance()\n        # Exact type: True and 1.0",
        "        seq = self._counter._next\n        # Exact type: True and 1.0",
        "every command consumes exactly one seq (D-03)",
    ),
    Mutant(
        "unfilled-purpose-wrong",
        _ENGINE,
        "purpose=CancelPurpose.UNFILLED,",
        "purpose=CancelPurpose.REQUESTED,",
        "a market remainder is cancelled as UNFILLED (D-08, D-10)",
    ),
    # Self-trade prevention
    Mutant(
        "stp-policies-swapped",
        _ENGINE,
        "if order.stp_policy is StpPolicy.CANCEL_NEWEST:",
        "if order.stp_policy is StpPolicy.CANCEL_OLDEST:",
        "each STP policy does its own thing (D-18)",
    ),
    Mutant(
        "stp-ignores-group",
        _ENGINE,
        "and resting.stp_id == order.stp_id",
        "and resting.stp_id is not None",
        "STP applies only within one stp_id (D-18)",
    ),
    Mutant(
        "stp-id-zero-falsy",
        _ENGINE,
        "                order.stp_id is not None\n"
        "                and order.stp_policy is not None",
        "                order.stp_id\n"
        "                and order.stp_policy is not None",
        "stp_id 0 is a real group (D-09 B5)",
    ),
    # Input validation
    Mutant(
        "float-cancel-id-accepted",
        _ENGINE,
        "if type(order_id) is int",
        "if order_id is not None",
        "cancel ids must be exact ints: 3.0 and True are rejected (D-09)",
    ),
    Mutant(
        "side-type-unchecked",
        _ENGINE,
        "if type(side) is not Side:",
        "if side is None:",
        'the string "buy" is not a Side and must be rejected (D-09)',
    ),
    Mutant(
        "stp-id-bool-accepted",
        _ENGINE,
        "if stp_id is not None and type(stp_id) is not int:",
        "if stp_id is not None and not isinstance(stp_id, int):",
        "stp_id must be an exact int: True is rejected (D-09 rule 1)",
    ),
    Mutant(
        "price-bool-accepted",
        _TYPES,
        "    if type(raw) is not int:\n        return RejectReason.PRICE_NOT_INTEGER",
        "    if not isinstance(raw, int):\n"
        "        return RejectReason.PRICE_NOT_INTEGER",
        "price must be an exact int: True is rejected (D-09 rule 1)",
    ),
    Mutant(
        "price-zero-accepted",
        _TYPES,
        "    if raw <= 0:\n        return RejectReason.PRICE_NOT_POSITIVE",
        "    if raw < 0:\n        return RejectReason.PRICE_NOT_POSITIVE",
        "price must be positive: 0 is rejected (D-02)",
    ),
)
