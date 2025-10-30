# Crypto Matching Engine

A fast, price–time–priority matching engine with trade‑through protection, real‑time market data (WebSocket), and a minimal REST API. Includes a reproducible benchmark suite and tests.

## Key features
- Price–time priority with FIFO per price level
- Trade‑through protection and common order types: limit, market, IOC, FOK
- BBO, depth, and trade streams over WebSocket
- Simple REST API for order entry and market data
- Deterministic benchmarks and unit tests

Architecture
- Matching engine keeps two book sides (bids/asks) with FIFO queues per price level.
- Price discovery uses heaps (min-heap for asks, max-heap via negation for bids) for O(log N) inserts/deletes.
- Concurrency via ThreadPoolExecutor; per-symbol locks guard book mutations; async layer publishes market data/trades.


```mermaid path=null start=null
flowchart TD
  Client -->|REST /orders| API[FastAPI]
  Client -->|WS /ws/marketdata| API
  Client -->|WS /ws/trades| API
  API -->|submit()| Engine[MatchingEngine]
  Engine -->|locks + heaps| Books[(OrderBooks)]
  Engine -->|trades| PubSub
  PubSub -->|push| Client
```

- Two book sides (bids/asks); FIFO queues per price level
- Heaps for price discovery: min-heap (asks), max-heap via negation (bids)
- Per‑symbol locks guard mutations; background tasks publish updates

## Project layout
```
src/app/                # API + engine
src/app/engine/         # Matching core (order book, levels)
performance/            # Benchmark scripts + results
scripts/                # Dev helpers (Windows PowerShell)
tests/                  # Unit tests
```

## Quick start
Windows PowerShell (recommended):
```
./scripts/setup.ps1      # create venv and install deps
./scripts/run.ps1 -Reload
```

Alt (any OS):
```
python -m pip install -r requirements.txt
python -m uvicorn --app-dir src app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API reference
Base URL: http://localhost:8000

- POST /orders — submit order
- GET  /bbo — best bid/offer for a symbol
- GET  /depth — top N depth for a symbol
- WS   /ws/marketdata?symbol=SYMBOL — market data snapshots
- WS   /ws/trades?symbol=SYMBOL — executed trades stream

Submit order (limit):
```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC-USDT",
    "order_type": "limit",
    "side": "buy",
    "quantity": 0.5,
    "price": 65000
  }'
```

Best bid/offer:
```bash
curl "http://localhost:8000/bbo?symbol=BTC-USDT"
```

Depth (top 10):
```bash
curl "http://localhost:8000/depth?symbol=BTC-USDT&levels=10"
```

WebSockets:
- Market data: ws://localhost:8000/ws/marketdata?symbol=BTC-USDT
- Trades:      ws://localhost:8000/ws/trades?symbol=BTC-USDT

## Benchmarking
Run local engine benchmark:
```bash
python performance/bench_local_engine.py --n 10000 --concurrency 400 --seed 42
```
Example output (on a laptop):
- orders: 10,000, concurrency: 400
- duration: ~2.95s, throughput: ~3,390 ops/s
- latency (ms): avg ~113, p50 ~110, p90 ~124, p99 ~196
- status: filled ~4,983, accepted ~4,272, canceled ~745

Results are saved in performance/results/.

## Testing
```bash
python -m pytest -q tests
```

## Development tips
- Prefer integer prices/quantities in minor units to avoid FP drift
- Keep long‑running I/O off the matching thread; publish updates asynchronously
- Profile with realistic mixes of orders (limit/market/IOC/FOK)

## Troubleshooting
- Mermaid diagrams require GitHub’s fenced block: ```mermaid (no extra tokens)
- On Windows, use the provided PowerShell scripts under scripts/
- If ports are busy, change uvicorn port with --port 8001

## Roadmap
- Cross‑symbol netting and risk checks
- Persistent event log and recovery
- Multi‑instrument order routing

## License
No license specified. Add a LICENSE file if you intend to share or open‑source.
