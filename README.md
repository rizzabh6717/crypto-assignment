# Crypto Matching Engine (Python)

A high-performance, price-time-priority matching engine with trade-through protection, real-time market data, and benchmarking suite.

Project structure
- src/app/... — application and engine code (FastAPI + matching engine)
- tests/ — unit tests
- performance/ — benchmark scripts

Architecture
- Matching engine keeps two book sides (bids/asks) with FIFO queues per price level.
- Price discovery uses heaps (min-heap for asks, max-heap via negation for bids) for O(log N) inserts/deletes.
- Concurrency via ThreadPoolExecutor; per-symbol locks guard book mutations; async layer publishes market data/trades.

graph TD;
  Client -->|REST /orders| API[FastAPI]
  Client -->|WS /ws/marketdata| API
  Client -->|WS /ws/trades| API
  API -->|submit()| Engine[MatchingEngine]
  Engine -->|locks + heap book| Books[(OrderBooks)]
  Engine -->|trades| PubSub
  PubSub -->|push| Client
```

Quick start (Windows PowerShell)
1) Setup venv and install deps
   ./scripts/setup.ps1

2) Run the API server
   ./scripts/run.ps1 -Reload

Alt (without scripts)
- python -m pip install -r requirements.txt
- python -m uvicorn --app-dir src app.main:app --host 0.0.0.0 --port 8000 --reload

API usage
Submit order
```bash path=null start=null
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

Best bid/offer
```bash path=null start=null
curl "http://localhost:8000/bbo?symbol=BTC-USDT"
```

Depth (top 10)
```bash path=null start=null
curl "http://localhost:8000/depth?symbol=BTC-USDT&levels=10"
```

WebSocket streams
- Market data snapshots: ws://localhost:8000/ws/marketdata?symbol=BTC-USDT
- Trades: ws://localhost:8000/ws/trades?symbol=BTC-USDT

Benchmarking
Local engine (in-process) benchmark:
```bash path=null start=null
python performance/bench_local_engine.py --n 10000 --concurrency 400 --seed 42
```
Results (sample on a laptop):
- orders: 10,000, concurrency: 400
- duration: 2.950s, throughput: 3,390 ops/s
- latency (ms): avg=112.834, p50=109.677, p90=123.728, p99=196.027
- status: filled=4983, accepted=4272, canceled=745

Testing
```bash path=null start=null
python -m pytest -q tests
```

Technology stack
- FastAPI for REST/WS API
- Heaps (heapq) for price discovery; FIFO deques per level
- ThreadPoolExecutor for CPU-bound matching; asyncio for I/O and publishing
- pytest + pytest-asyncio for tests

Notes
- Supports Market, Limit, IOC, FOK
- Enforces price-time priority and trade-through protection
- Logs JSON-like lines to stdout
