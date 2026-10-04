# Matching Engine

Single-instrument limit order book and matching engine in Python.
Single-threaded, deterministic, in-memory, price-time priority.

## Features

- Limit and market orders, cancel by order ID
- Price-time priority; time is a monotonic sequence counter, not the wall clock
- Trades execute at the resting order's price
- Partially filled resting orders keep their queue position
- Market orders fill what they can and cancel the remainder; they never rest
- Invalid input produces an explicit `Rejected` event with a reason
- Opt-in self-trade prevention (`stp_id`): Cancel Newest or Cancel Oldest
- Integer prices and quantities (ticks, lots); no floats

Full behavior is specified in [SPEC.md](SPEC.md).

## Design

| Component | Implementation | Rationale |
|---|---|---|
| Price levels | `SortedDict` per side | Ordered levels, direct best-price access |
| Level queue | Doubly linked list | O(1) FIFO append/pop and O(1) unlink |
| Cancel | Eager removal via order ID → node index | No tombstones; book state is always exact |
| Output | `list[Event]` per command: `Trade`, `Rested`, `Cancelled`, `Rejected` | Typed; each event carries its command's sequence number; book is reconstructible from events |
| Determinism | No global state, clock, or randomness | Same command stream → same event stream |

Alternatives and tradeoffs: [DECISIONS.md](DECISIONS.md).

## Requirements

- Python 3.14+
- `sortedcontainers`

## Installation

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

Unit tests plus Hypothesis stateful tests. The engine state machine rebuilds
the book from emitted events and checks, after every command: price-time
priority, quantity conservation, self-trade prevention, and an uncrossed book.

## Project Layout

```
src/matching_engine/   engine, book, order index, events, types, sequencer
tests/unit/            unit tests
tests/stateful/        Hypothesis state-machine tests
reference/             independent reference engine (planned)
sim/                   seeded order generator and replay (planned)
bench/                 benchmarks (planned)
```

## Roadmap

- [x] Limit matching, market orders, cancel, self-trade prevention
- [ ] Complete reject taxonomy
- [ ] Reference engine and differential testing
- [ ] Seeded simulation, replay, and benchmarks
