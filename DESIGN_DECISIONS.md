# Architecture Decisions

Design decisions for a single-instrument, single-threaded, deterministic limit
order book and matching engine (price-time priority).

| ID   | Decision                                  | Status      |
| ---- | ----------------------------------------- | ----------- |
| D-01 | Language and tooling                      | Implemented |
| D-02 | Numeric representation                    | Implemented |
| D-03 | Sequence counter                          | Implemented |
| D-04 | Book structure per side                   | Implemented |
| D-05 | Price-level container                     | Implemented |
| D-06 | Cancel strategy and order-ID index        | Implemented |
| D-07 | Trade price and trade record              | Implemented |
| D-08 | Market-order remainder                    | Implemented |
| D-09 | Input validation and reject taxonomy      | Implemented |
| D-10 | Event schema                              | Implemented |
| D-11 | Partial fills and queue position          | Implemented |
| D-12 | Engine API                                | Implemented |
| D-13 | Reference engine and differential testing | Implemented |
| D-14 | Replay log format                         | Open        |
| D-15 | Mutation testing approach                 | Open        |
| D-16 | Benchmark methodology                     | Open        |
| D-17 | Order representation                      | Implemented |
| D-18 | Self-trade prevention                     | Implemented |

---

## D-01: Language and tooling

**Decision:** Python 3.14 with pytest, Hypothesis, ruff and `mypy --strict`.

**Why:** Hypothesis gives mature stateful property testing, which the
verification strategy depends on. Python allows faster iteration than C++ or
Rust for a correctness-first project.

---

## D-02: Numeric representation

**Decision:**

- `Price`, `Quantity`, `OrderId`, `SeqNo` are `NewType` wrappers over `int`.
  Prices are in ticks, so there is no separate tick-size concept.
- No upper bound on price or quantity. Only values `<= 0` are rejected.
- `qty` and `remaining` share the `Quantity` type.
- `make_price` / `make_quantity` return the value or a reject reason, never raise.

**Why:**

- `NewType` lets mypy catch Price/Quantity mix-ups at no runtime cost.
- Prices are already stored in ticks, so a `TICK_SIZE > 1` would guard a case
  that cannot occur.
- Python ints don't overflow and the engine is single-instrument, so a bound
  has nothing to protect. Bounded search spaces belong in test strategies.
- Returning the reason lets mypy force callers to handle failure while keeping
  the reject reason the spec requires. A raised exception is invisible to
  the type checker.

**Rejected:**

- Plain alias: no type safety.
- Frozen validating dataclass: arithmetic boilerplate on every fill.
- UUID order IDs: need their own seeded generator to stay deterministic.

---

## D-03: Sequence counter

**Decision:** One global, instance-scoped counter (`SeqCounter`). **Every
command consumes exactly one `SeqNo`**: new order or cancel, accepted or
rejected. Every event carries the seq of the command that caused it.
`OrderId` is minted as `OrderId(seq)`.

**Why:** `SeqNo` is the position in the command stream, so each event maps to
exactly one command. A rejected cancel still needs a position for its
`Rejected` event, and the reference engine and replay both need every command
placed in the stream.

**Trade-off:** `OrderId`s are gapped by rejects and cancels, so a gap has no
single cause. The event log, where each seq appears once, answers "what
happened at seq N".

**History:** The first design ticked only on new orders. Review showed cancels
were invisible: `cancel` returned a bare `bool`, unknown-ID cancels couldn't
produce a `Rejected`, and the event stream couldn't rebuild the book.

**Open:** Whether a future Amend that loses priority gets a fresh priority
seq while keeping its `OrderId`.

**Tests:** `tests/unit/test_sequencer.py`, `tests/unit/test_matching.py`
(cancel seq tests), and a stateful check that each command consumes one seq.

---

## D-04: Book structure per side

**Decision:** One `SortedDict` (sortedcontainers) per side, keyed by price.
Best price via `peekitem`; `depth()` iterates in order.

**Why:** It provides ordered iteration, cheap best-price lookup and cheap
insert/delete of levels without hand-written tree code.

**Rejected:**

- Heap: one extremum only, and no ordered iteration for `depth()` without
  destroying it.
- `dict` + `bisect` list: O(n) insert/delete of price levels on the hot path.
- Hand-rolled balanced tree: rotation bugs for no gain.
- One combined structure for both sides: no asymptotic win, less readable.

**Caveat:** `sortedcontainers` documents insert/delete as roughly O(√n)
internally (a list of sorted sublists), not O(log n). Not benchmarked; revisit
in the benchmark phase (D-16).

---

## D-05: Price-level container

**Decision:** A doubly-linked list of private `_Node`s per level (`head` /
`tail`), with the order-ID index (D-06) mapping `OrderId` to its node.
Append, pop-front and cancel are all O(1).

**Why:** Cancel removes from the middle of a queue. A `deque` or `list` needs a
linear scan for that, and an index of positions can't help because positions
shift on every pop. A direct node reference makes the splice touch only two
neighbours.

**Design notes:**

- Links live on a `_Node` wrapper, not on `LimitOrder`, so the dataclass's
  generated `__eq__` doesn't recurse through book neighbours. `_Node` uses
  `eq=False, repr=False` for the same reason.
- `OrderHandle.removed` guards against double removal through a stale handle
  (found by hand review, see DESIGN.md).
- `Book.front_handle(side)` returns the handle, so matching can remove an order
  without a second index lookup.
- The cache-locality argument for arrays over linked lists doesn't transfer to
  CPython: a `list` holds pointers to separately allocated objects either way.
  The real difference is that `list.pop(0)` and mid-removal cost an O(n)
  `memmove`.

**Trade-off:** Four hand-written removal cases (empty level, head, tail, sole
element) are a known bug surface. They are covered by unit tests and the
Hypothesis stateful tests, including a FIFO-order invariant.

**Tests:** `tests/unit/test_book.py`, `tests/stateful/test_book_stateful.py`.

---

## D-06: Cancel strategy and order-ID index

**Decision:**

- **Index:** a standalone `OrderIndex` (`register` / `lookup` / `forget`),
  owned by the engine alongside the `Book`.
- **Cancel:** eager. Look up the handle, splice it out of the level, forget it
  in the index.
- `remove_order(book, index, order_id)` is the single helper that keeps book
  and index in sync. Both cancel and the matching loop's full-fill path use it.

**Why:**

- Lazy deletion exists to avoid expensive physical removal, and D-05 already
  makes removal O(1). Laziness would only add bookkeeping: per-level live
  quantity, and a best-price lookup that skips dead levels.
- Lazy deletion also pays off in concurrent engines, which this is not.
- A separate `OrderIndex` keeps `Book` free of `OrderId` knowledge and can be
  tested without constructing a book.

**Rejected:** index inside `Book` (mixes responsibilities); a bare `dict` on
the engine (valid, but less testable); hybrid lazy/eager (all the complexity,
no benefit).

**Would revisit if:** concurrency entered scope.

**Tests:** `tests/unit/test_order_index.py`, `tests/unit/test_engine.py`
(`remove_order`), `tests/stateful/test_engine_stateful.py` (`is_resting`
agrees with the event-rebuilt book).

---

## D-07: Trade price and trade record

**Decision:** Trades print at the **resting order's price**. `Trade` carries
`resting_order_id`, `incoming_order_id` and `aggressor_side`.

**Why:** The resting order posted a firm, displayed price, and the aggressor
accepted it. The price must not depend on who arrived second. A midpoint can
be non-integer, which the integer-tick rule forbids.

`resting` / `incoming` plus `aggressor_side` carries strictly more than
buy / sell IDs: the buyer and seller can be derived from it, but not which
order was passive.

**Would revisit if:** an auction / uncross mode were added (needs a single
clearing price).

**Tests:** `tests/unit/test_matching.py` (resting-price, multi-level walk,
aggressor side); the stateful test checks every `Trade.price` against the
rebuilt book.

---

## D-08: Market-order remainder

**Decision:** A market order fills what it can, then emits
`Cancelled(purpose=UNFILLED)` for the rest. On an empty book that is the full
quantity. It never rests.

**Why:** A market order on an empty book is valid input with an outcome of
"nothing to fill". `Rejected` means invalid input; mixing in market state
would make the same order valid or invalid depending on the book.
Market-to-limit conversion would make a market order rest.

**Known gap:** No price protection. A large market order sweeps every
reachable level. Real venues usually add price bands (out of scope).

**Interaction:** If self-trade prevention stops a market order, the remainder
is `Cancelled(purpose=SELF_TRADE_PREVENTED)` (D-18).

---

## D-09: Input validation and reject taxonomy

Rejects consume a seq (D-03). A reject is the only event for its command and
changes no state.

**Validation rules** (checked in this order):

1. `side` is exactly `Side`.
2. `price` is exactly `int` and `> 0`.
3. `quantity` is exactly `int` and `> 0`.
4. `stp_id` is exactly `int` when set; any value is valid, including 0 and negatives.
5. `stp_policy` is exactly `StpPolicy` when set.
6. `stp_id` and `stp_policy` are set together or not at all.
7. Cancel `order_id` is exactly `int` and currently resting.

**Reasoning:**

- **Exact-type checks (`type(x) is int`):** mypy only protects typed callers;
  replay files and generators pass whatever they parsed. Without the check,
  `price=100.5` rested at 100.5, `price=True` rested at `True`, and
  `cancel(1.0)` cancelled order 1 (`True == 1.0 == 1` and they hash alike), so
  no `==`-based container can catch it. The check sits at the engine boundary.
  Coercing was rejected because it changes the client's request silently.
  Cost: `int` subclasses (`IntEnum`, numpy ints) are rejected too.
- **STP fields together:** an `stp_id` alone protected a resting order but not
  an aggressing one; a policy alone has no group to match. Defaulting a policy
  would invent a client instruction.
- **`stp_id` range:** any exact `int`. The engine only compares it with `==`,
  so a sign rule would protect nothing. The alternative (positive only) is
  backward compatible to loosen later; revisit if external clients or a venue
  spec reserved ids.
- **Cancel rejects** don't distinguish unknown, filled or already-cancelled
  ids. Distinguishing them would need a per-id tombstone with unbounded memory.

**Reject reasons are enum codes, not strings.** `Rejected.reason` is a
`RejectReason`:

| Code                  | Meaning                                    |
| --------------------- | ------------------------------------------ |
| `SIDE_INVALID`        | side is not a `Side`                       |
| `PRICE_NOT_INTEGER`   | price is not an exact `int`                |
| `PRICE_NOT_POSITIVE`  | price `<= 0`                               |
| `QTY_NOT_INTEGER`     | quantity is not an exact `int`             |
| `QTY_NOT_POSITIVE`    | quantity `<= 0`                            |
| `STP_ID_INVALID`      | `stp_id` is not an exact `int`             |
| `STP_POLICY_INVALID`  | `stp_policy` is not a `StpPolicy`          |
| `STP_FIELDS_MISMATCH` | only one of `stp_id` / `stp_policy` set    |
| `ORDER_NOT_RESTING`   | cancel target is not resting (or mistyped) |

Why codes: the reference engine's events are compared to the engine's by
equality, and free text couples two engines on wording. The engine is a
deterministic function of the command log and `seq` maps each event to one
command, so copying the offending value into the event is redundant data that
can disagree with its source. A per-reason event class also fails comparison
for NaN payloads, because a dataclass holding `float('nan')` is unequal to
itself (verified on 3.14).

**Cancel rejects carry no `order_id`.** An event carries what is needed to
rebuild the book from the stream: `Cancelled` changes the book so it names the
order, but a reject changes nothing. The id is already in the command.
Real venues echo it, because clients lack the venue's command log, so this
changes if events reach a consumer without the command log (see D-14).

**Tests:** `tests/unit/test_types.py`, `tests/unit/test_matching.py`
(per-rule and check-order tests), stateful and differential tests with
generators emitting every invalid kind.

---

## D-10: Event schema

**Decision:** `Event = Trade | Rested | Cancelled | Rejected`, distinct frozen
dataclasses. Every command returns a flat, ordered `list[Event]`. All events
carry the `seq` of the command that caused them.

| Event       | Fields                                                                           |
| ----------- | -------------------------------------------------------------------------------- |
| `Trade`     | `seq`, `price`, `qty`, `resting_order_id`, `incoming_order_id`, `aggressor_side` |
| `Rested`    | `seq`, `order_id`, `side`, `price`, `remaining`                                  |
| `Cancelled` | `seq`, `order_id`, `remaining`, `purpose`                                        |
| `Rejected`  | `seq`, `reason`                                                                  |

`CancelPurpose` is `REQUESTED`, `UNFILLED` or `SELF_TRADE_PREVENTED`.

**Why:**

- **Tagged union over one class with optional fields:** mypy then guarantees
  which fields exist for which outcome, and `match` can be checked for
  exhaustiveness.
- **Over untyped dicts:** serialization is better handled by a `to_dict()`
  layer on top of the typed events, built when needed (D-14).
- **Flat list:** one command can produce several trades plus a rest. A nested
  per-command result type would need its own union and still has to flatten
  for logging. A flat list also makes the engine-vs-reference comparison a
  plain list equality.
- **Shared seq, no per-event ID counter:** no persistence requirement yet.
- **One `Cancelled` with a `purpose`:** a requested cancel and a market
  remainder are the same fact with different causes.
- **No `Accepted` event:** every accepted command emits at least one of
  `Trade`, `Rested` or `Cancelled`.
- **Self-describing events:** `Rested` carries `side` and `Trade` carries
  `aggressor_side` (the resting side is the opposite), so the book can be
  rebuilt from the event stream alone.

**Would revisit if:** a consumer must handle `Cancelled` without having seen
the `Rested` (then add `side` / `price`), or Amend adds another order-exit
path.

**Tests:** `tests/unit/test_events.py`; the stateful test rebuilds the book
from events and compares it to `Engine.depth` after every command.

---

## D-11: Partial fills and queue position

**Decision:** A partially filled resting order **keeps its queue position**.
`remaining` is a mutable field decremented in place; the original `qty` is
retained.

**Why:** Time priority is based on arrival, which a partial fill doesn't
change. With in-place mutation the matching loop never moves the node, so
keeping position costs nothing. Frozen-and-replace would require re-inserting
at the same spot and repointing the index. Deriving remaining from fill history
is O(fills) for a value read on every loop iteration.

**Open:** A future Amend would likely keep priority on a quantity reduction
and lose it on an increase or price change, which needs a move-to-back
operation the book doesn't have.

**Tests:** `tests/unit/test_matching.py`; the stateful test checks that every
trade hits the front of the rebuilt book and that partial fills keep their
original seq.

---

## D-12: Engine API

**Decision:** A stateful `Engine` class with separate methods
(`submit_limit_order`, `submit_market_order`, `cancel`), each returning
`list[Event]`. State (`_book`, `_index`, `_counter`) is private. Reads go
through `best_bid()`, `best_ask()`, `depth(side)` and `is_resting(order_id)`,
which return values, never internal objects.

**Why:**

- Free functions threading `book`, `index` and `counter` became unwieldy once
  the third dependency arrived.
- Private state prevents callers from bypassing `remove_order` and drifting
  the book and index apart. The module-level `cancel` function was deleted
  because it was a second path that emitted no events and consumed no seq.
- Returning copies of the book per query costs a copy for no benefit in a
  single-threaded engine. Python privacy is a convention, so the goal is to
  make the wrong path visibly wrong, not impossible.
- `remove_order` stays module-level as the atomic helper, tested directly.

**Deferred:** A single `process(command)` entry point needs a `Command` union.
It will likely be forced by replay tooling, at which point the existing
methods become thin wrappers.

**Related:** The design is a single synchronous processor over a journalled
command log, as in LMAX's business-logic processor. That means replay only ever
needs to serialize commands, never book state (D-14).

---

## D-13: Reference engine and differential testing

**Why it exists:** The stateful tests show the engine is consistent with
itself. They can't catch events that are self-consistent but wrong, such as a
trade at the aggressor's price. An independent second implementation can.

**Decision:**

- **Scope:** `reference/naive_engine.py` covers the whole SPEC: limit, market,
  cancel, both STP policies, every reject and the validation order.
- **Written from SPEC.md only**, then reviewed line by line.
- **Comparison after every command:** full event list (`==`) plus
  `depth(BUY)` / `depth(SELL)`. Depth catches state divergence that no event
  shows (for example a cancel that emits the right `Cancelled` but leaves the
  order in its level). An exception from either engine is a failure.
- **Shared code:** data shapes only (event dataclasses, `NewType`s, `Side`,
  `StpPolicy`, `CancelPurpose`) and no logic. Sharing validation would make
  reject paths agree by construction.
- **Inputs:** `@given(st.lists(command))` over a narrow price band, small
  quantities, a few STP ids, cancel ids overlapping live orders, and about 10%
  invalid values. A failure prints a command list, which is directly a repro.
  `hypothesis.event()` statistics measure how often trades, STP cancels,
  successful cancels and rejects occur.

**Risks:**

- Both engines come from one SPEC, so a SPEC error is invisible here. Invariant
  checks and review cover that.
- Blind cancel ids may rarely hit a live order; switch to a state machine if so.
- Compare every N steps if the naive engine is too slow for long runs.

**Tests:** `tests/differential/test_differential.py`,
`tests/invariants/checker.py`.

---

## D-17: Order representation

**Decision:**

- `LimitOrder | MarketOrder` is a tagged union. Only `LimitOrder` has `price`.
- Orders are plain mutable dataclasses.
- `time_in_force` and `post_only` are not modelled yet.
- Amend, when built, is a top-level engine operation beside Cancel.

**Why:**

- With the union, `Book`'s storage type admits only `LimitOrder`, which
  removes a class of "may this order be here" checks (a market order never
  rests).
- Fields with a single valid value would burden every consumer for no
  behaviour. Adding a defaulted field once the feature exists is a small,
  mechanical change.
- Amend acts on an existing order and doesn't need its own order shape.
- Mutable orders avoid replace-on-fill bookkeeping (D-11). "No global mutable
  state" concerns the engine as a function of its inputs, not object-level
  immutability.

---

## D-18: Self-trade prevention

**Decision:**

- In scope and opt-in per order via `stp_id` and `stp_policy`
  (`kw_only`, default `None`).
- Orders sharing an `stp_id` never trade with each other.
- Policies: **Cancel Newest** and **Cancel Oldest**. The **incoming order's
  policy governs**.
- Both fields must be set together (D-09).

**Policy behaviour:**

- **Cancel Newest:** stop matching and cancel the incoming remainder
  (`SELF_TRADE_PREVENTED`). It cannot rest instead: a resting same-owner order
  on each side at one price would cross the book.
- **Cancel Oldest:** remove the resting order via `remove_order` (O(1) by
  handle, D-05/D-06), re-read the front of the book and continue.

**Why:**

- **Opt-in `stp_id` over a blanket account rule:** real venues use per-order
  group ids, since a firm's independent desks may legitimately cross. (From
  general knowledge of exchange rules, not checked against a specific
  rulebook.)
- **Incoming policy only:** avoids a tie-break when the two orders' policies
  conflict.
- **`kw_only` fields:** `LimitOrder.price` has no default and follows them in
  the base class, and `kw_only` is exempt from the dataclass ordering
  constraint. Existing construction sites are unchanged.

**Not built:** Cancel Both, which would be a third branch in the same
structure.

**Tests:** `tests/unit/test_matching.py` (`test_self_trade_prevention_*`,
`test_cancel_newest_*`, `test_cancel_oldest_*`); the stateful test checks that
no trade pairs the same `stp_id` and that every Cancel Oldest removal is the
front of the book.

---

## Open decisions

- **D-14: Replay log format.** The log needs commands only, rejected ones
  included, so rejects can be explained after the fact (D-09). It will
  serialize the typed command and event shapes (D-10, D-12).
- **D-15: Mutation testing.** Approach and number of injected bugs. The
  `mutation/` directory is a work in progress.
- **D-16: Benchmark methodology.** What to measure and on what workload,
  including the `SortedDict` complexity caveat in D-04.
