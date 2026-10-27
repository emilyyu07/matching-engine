# Matching Engine

Single-instrument limit order book and matching engine in Python.
Single-threaded, deterministic, in-memory, price-time priority.

## Behavior

- Limit and market orders; cancel by order ID
- Price-time priority; ordering uses a monotonic sequence counter, not wall-clock time
- Trades execute at the resting order's price
- Partially filled resting orders keep their queue position
- Market orders fill what they can and cancel the remainder; they never rest
- Invalid input produces a `Rejected` event with an enum reason code
- Opt-in self-trade prevention (`stp_id`): Cancel Newest or Cancel Oldest
- Integer prices and quantities (ticks, lots)

## Design

| Component | Implementation | Rationale |
|---|---|---|
| Price levels | `SortedDict` per side | Ordered levels, direct best-price access |
| Level queue | Doubly linked list | O(1) append, pop-front and unlink |
| Cancel | Eager removal via order ID index | No tombstones; book contains only live orders |
| Output | `list[Event]` per command: `Trade`, `Rested`, `Cancelled`, `Rejected` | Typed; each event carries its command's sequence number; book can be rebuilt from events |
| Determinism | No global state, clock or randomness | Same command stream produces the same event stream |

Full architectural decisions, alternatives and trade-offs: [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).

## Setup

Requires Python 3.14+.

```bash
pip install -e ".[dev]"
```

## Usage

```python
from matching_engine.engine import Engine
from matching_engine.types import OrderId, Side

e = Engine()
e.submit_limit_order(Side.SELL, 100, 5)  # [Rested(order_id=1, side=SELL, ...)]
e.submit_limit_order(Side.BUY, 101, 3)   # [Trade(price=100, qty=3, ...)]
e.cancel(OrderId(1))                     # [Cancelled(remaining=2, purpose=REQUESTED, ...)]
e.best_ask()
e.depth(Side.SELL)
```

## Testing

```bash
make test        # pytest
make fast        # skip slow tests
make lint        # ruff check + format check
make typecheck   # mypy --strict
```

- **Unit tests** for the book, order index, sequencer, events, types and matching.
- **Stateful tests** (Hypothesis) rebuild the book from emitted events and check
  after every command: price-time priority, quantity conservation,
  self-trade prevention and an uncrossed book.
- **Differential tests** compare events and book depth against an independent
  reference engine (`reference/`) on random command streams, including invalid inputs.
- **Mutation harness** (`mutation/`) injects known bugs and reports which
  ones the test suite fails to catch.

## Layout

```
src/matching_engine/   engine, book, order index, events, types, sequencer
reference/             naive reference engine
tests/                 unit, stateful, differential and invariant tests
mutation/              mutation harness
sim/                   seeded command generator
```
