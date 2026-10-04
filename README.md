# Matching Engine

A correctness-first limit order book and matching engine for a single
instrument: single-threaded, deterministic, in-memory, price-time priority.
Built to be explained, not just to run.

## Semantics

- Integer prices and quantities (ticks, lots). No floats.
- Price-time priority; time = a monotonic sequence counter, never the clock.
- Trades execute at the **resting** order's price.
- Partially filled resting orders keep their queue position.
- Market orders fill what they can and cancel the rest. They never rest.
- Invalid input → an explicit `Rejected` event with a reason.
- Opt-in self-trade prevention (`stp_id`): Cancel Newest or Cancel Oldest.

Canonical behavior: [SPEC.md](SPEC.md).

## Design

| Concern | Choice | Why |
|---|---|---|
| Price levels per side | `SortedDict` | Fast best price, ordered depth |
| Orders within a level | Doubly linked list | O(1) FIFO and O(1) cancel by handle |
| Cancel | Eager removal via ID → handle index | No tombstones; the book is always exact |
| Output | `list[Event]` per command (`Trade` / `Rested` / `Cancelled` / `Rejected`) | Typed union; every event carries its command's seq; the book can be rebuilt from events alone |
| Determinism | No global state, clock or randomness | Same commands → same events |

Rationale, rejected alternatives and tradeoffs: [DECISIONS.md](DECISIONS.md).

## Usage

```python
from matching_engine.engine import Engine
from matching_engine.types import OrderId, Side

e = Engine()
e.submit_limit_order(Side.SELL, 100, 5)  # [Rested(order_id=1, side=SELL, ...)]
e.submit_limit_order(Side.BUY, 101, 3)  # [Trade(price=100, qty=3, ...)]
e.cancel(OrderId(1))  # [Cancelled(remaining=2, purpose=REQUESTED, ...)]
e.best_ask(), e.depth(Side.SELL)  # read-only queries
```

## Development

```bash
pip install -e ".[dev]"
make test        # pytest
make lint        # ruff
make typecheck   # mypy --strict
```

Tests: unit tests, plus Hypothesis stateful tests for the book (FIFO within a
level) and the engine (rebuilds the book from events and checks price-time
priority, quantity conservation, self-trade prevention and a never-crossed
book after every command).

## Status

Matching, market orders, cancel and self-trade prevention are implemented.
Next: reject taxonomy (D-09), an independent reference engine for
differential testing, replay tooling.
