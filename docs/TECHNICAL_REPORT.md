# Matching Engine: Technical Report and API Guide

Overview
- A Python FastAPI service exposing a high-performance, price-time-priority matching engine with live market data and trade feeds.
- Goals: correctness (FIFO within price, no trade-throughs), simplicity, strong baseline performance, and clear observability.

Project structure
- `src/app/main.py` — FastAPI app (REST + WebSockets), endpoints and request models
- `src/app/engine/order_book.py` — Matching engine: order book, matching logic, data structures, concurrency
- `tests/test_engine.py` — Behavioral tests (FIFO, IOC/FOK semantics, market behavior)
- `performance/bench_local_engine.py` — In-process benchmarking
- `performance/results/` — Saved benchmark outputs
- `tools/md.html`, `tools/trades.html` — Minimal WS viewers for market data and trades
- `scripts/setup.ps1`, `scripts/run.ps1`, `scripts/test.ps1` — Setup/Run/Test helpers

Architecture and data structures
- Sides and levels
  - Two sides per book: bids (buy) and asks (sell)
  - Each price level holds a FIFO queue of orders using a `deque` to enforce time-priority (first-in, first-out)
- Price discovery
  - Uses `heapq` for best-price retrieval in O(1) and updates in O(log N)
  - Asks: min-heap of prices; Bids: min-heap of negated prices (behaves as max-heap)
  - Lazy deletion: empty levels are removed from the map; stale heap entries get skipped when discovered
- Matching algorithm
  - BUY orders consume asks from lowest price upward; SELL orders consume bids from highest price downward
  - Limit/IOC/FOK enforce price boundaries; IOC/FOK never rest, FOK pre-check guarantees all-or-none
  - Remaining LIMIT quantity rests at its price level (FIFO within level)

Concurrency model
- Matching is CPU-bound: executed in a `ThreadPoolExecutor` (4 workers by default)
- Per-symbol locks protect each book from concurrent mutations while allowing parallelism across symbols
- Async layer (FastAPI event loop) remains responsive; market data snapshots and trades are published after state updates

Running the service
- Quick start (Windows PowerShell):
```bash path=null start=null
./scripts/setup.ps1
./scripts/run.ps1 -Reload
```
- Alternative (without scripts):
```bash path=null start=null
python -m pip install -r requirements.txt
python -m uvicorn --app-dir src app.main:app --host 127.0.0.1 --port 8000 --reload
```

HTTP API
- POST `/orders` — Submit an order
  - Request body fields: `symbol` (str), `order_type` (market|limit|ioc|fok), `side` (buy|sell), `quantity` (number), `price` (number? required for limit/ioc/fok)
  - Example (PowerShell-friendly):
```bash path=null start=null
$limit = @{symbol="BTC-USDT"; order_type="limit"; side="sell"; quantity=2; price=65500} | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/orders' -Method POST -ContentType 'application/json' -Body $limit
```
  - Example (curl.exe):
```bash path=null start=null
curl.exe -X POST http://127.0.0.1:8000/orders -H "Content-Type: application/json" -d '{"symbol":"BTC-USDT","order_type":"limit","side":"sell","quantity":2,"price":65500}'
```
  - Response fields: `status` (filled|accepted|canceled|rejected), `order_id`, `filled_quantity`, `remaining_quantity`, `trades` (array)
- GET `/bbo?symbol=...` — Best bid/offer
```bash path=null start=null
curl "http://127.0.0.1:8000/bbo?symbol=BTC-USDT"
```
- GET `/depth?symbol=...&levels=N` — Top N levels per side
```bash path=null start=null
curl "http://127.0.0.1:8000/depth?symbol=BTC-USDT&levels=10"
```

WebSocket API
- Market data snapshots: `/ws/marketdata?symbol=...`
  - Payload: `{ timestamp, symbol, bbo, asks: [[price,qty],...], bids: [[price,qty],...] }`
- Trades: `/ws/trades?symbol=...`
  - Payload: `{ timestamp, symbol, trade_id, price, quantity, aggressor_side, maker_order_id, taker_order_id }`

Live demonstration guide (3-window layout)
- Left: open `tools/md.html` (market data) in a browser
- Middle: open `tools/trades.html` (trades) in a browser
- Right: PowerShell terminal
  1) Start server (keep running):
```bash path=null start=null
./scripts/run.ps1 -Reload
```
  2) In a new PowerShell tab, submit a resting ask (watch Market Data update):
```bash path=null start=null
$limit = @{symbol="BTC-USDT"; order_type="limit"; side="sell"; quantity=2; price=65500} | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/orders' -Method POST -ContentType 'application/json' -Body $limit
```
  3) Create a trade (watch Trades + Market Data update):
```bash path=null start=null
$market = @{symbol="BTC-USDT"; order_type="market"; side="buy"; quantity=0.5} | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/orders' -Method POST -ContentType 'application/json' -Body $market
```
  4) Inspect book state:
```bash path=null start=null
iwr -UseBasicParsing 'http://127.0.0.1:8000/bbo?symbol=BTC-USDT'
iwr -UseBasicParsing 'http://127.0.0.1:8000/depth?symbol=BTC-USDT&levels=5'
```
  Tips
  - If quoting is tricky, use Swagger UI at `http://127.0.0.1:8000/docs` to POST `/orders`
  - To reset quickly, use a fresh symbol (e.g., `ETH-USDT`) and repeat

Testing
- Run tests:
```bash path=null start=null
python -m pytest -q tests
```
- Covered behaviors: price-time priority (FIFO), IOC non-resting, FOK all-or-none, market orders respecting best price first

Benchmarking
- Local engine benchmark example:
```bash path=null start=null
python performance/bench_local_engine.py --n 10000 --concurrency 400 --seed 42
```
- Sample results (stored under `performance/results/`):
  - 10k @ 400 → ~3.3k ops/s; latency ms avg~113, p50~104, p90~158, p99~223
  - 50k @ 1000, deeper seed → ~3.0k ops/s; latency ms avg~318, p99~950

Design decisions (summary)
- Heaps for O(log N) price discovery; deques for O(1) FIFO at each price level
- Lazy heap deletion to avoid O(N) cleanup work
- ThreadPoolExecutor for CPU-bound matching with per-symbol locks to scale across cores
- Async PubSub keeps WebSocket broadcasting simple and non-blocking

Extensibility roadmap
- Order cancels/amends: index resting orders by id within each `PriceLevel`
- Risk/validation: add pre-trade checks before `_match`
- Persistence: append-only event log for recovery; optional snapshots
- Horizontal scale: shard symbols across processes or hosts; publish MD/Trades over a broker
- Performance: switch to fixed-point integers, Cython/Rust hot paths, or multiprocessing per-symbol actors
