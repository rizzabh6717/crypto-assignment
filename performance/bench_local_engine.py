#!/usr/bin/env python3
import os
import sys
import asyncio
import time
import random
import argparse
from collections import Counter
from decimal import Decimal

# Ensure we can import from src/
THIS_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(THIS_DIR, "../src")))

from app.engine.order_book import MatchingEngine, PubSub, Side, OrderType, dec  # noqa: E402


def pct(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


async def seed_book(engine: MatchingEngine, symbol: str, base: Decimal, spread: int, depth: int):
    # Create symmetric depth around base price so market/marketable orders can match
    tasks = []
    for i in range(1, depth + 1):
        ask_p = base + Decimal(str(i % (spread + 1)))
        bid_p = base - Decimal(str(i % (spread + 1)))
        tasks.append(engine.submit(symbol=symbol, order_type=OrderType.LIMIT, side=Side.SELL, quantity=dec("1.0"), price=ask_p))
        tasks.append(engine.submit(symbol=symbol, order_type=OrderType.LIMIT, side=Side.BUY, quantity=dec("1.0"), price=bid_p))
    await asyncio.gather(*tasks)


def make_order(symbol: str, base: Decimal, spread: int):
    side = Side.BUY if random.random() < 0.5 else Side.SELL
    r = random.random()
    if r < 0.6:
        order_type = OrderType.LIMIT
    elif r < 0.9:
        order_type = OrderType.MARKET
    else:
        order_type = OrderType.IOC

    qty = Decimal(str(round(random.uniform(0.1, 1.0), 3)))

    price = None
    if order_type != OrderType.MARKET:
        # Pick a price in a window around base; sometimes cross the spread to be marketable
        offset = Decimal(str(random.randint(-spread, spread)))
        price = base + offset
        # Nudge to be marketable half the time
        if random.random() < 0.5:
            price = base + (Decimal("1") if side == Side.BUY else Decimal("-1"))

    return dict(symbol=symbol, order_type=order_type, side=side, quantity=qty, price=price)


async def run_benchmark(n: int, concurrency: int, symbol: str, base: Decimal, spread: int, seed_depth: int, seed: int | None):
    if seed is not None:
        random.seed(seed)
    engine = MatchingEngine(PubSub())

    await seed_book(engine, symbol, base, spread, seed_depth)

    sem = asyncio.Semaphore(concurrency)
    lat_ms = []
    status_ctr = Counter()

    async def one(i: int):
        nonlocal lat_ms, status_ctr
        order = make_order(symbol, base, spread)
        async with sem:
            t0 = time.perf_counter()
            res = await engine.submit(**order)
            dt = (time.perf_counter() - t0) * 1000.0
            lat_ms.append(dt)
            status_ctr[res.get("status", "?")] += 1

    t_start = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(n)))
    total_s = time.perf_counter() - t_start

    throughput = n / total_s if total_s > 0 else 0.0

    print("=== Benchmark (local engine) ===")
    print(f"symbol: {symbol}")
    print(f"orders: {n}  concurrency: {concurrency}")
    print(f"duration: {total_s:.3f}s  throughput: {throughput:,.0f} ops/s")
    if lat_ms:
        avg = sum(lat_ms) / len(lat_ms)
        print("latency (ms): avg={:.3f} p50={:.3f} p90={:.3f} p99={:.3f}".format(
            avg, pct(lat_ms, 50), pct(lat_ms, 90), pct(lat_ms, 99)
        ))
    print("status counts:")
    for k, v in status_ctr.most_common():
        print(f"  {k:>8}: {v}")


def main():
    ap = argparse.ArgumentParser(description="Benchmark the matching engine via direct calls")
    ap.add_argument("--n", type=int, default=5000, help="total number of orders")
    ap.add_argument("--concurrency", type=int, default=200, help="concurrent in-flight orders")
    ap.add_argument("--symbol", type=str, default="BTC-USDT")
    ap.add_argument("--base", type=Decimal, default=Decimal("100"), help="base price around which to generate limits")
    ap.add_argument("--spread", type=int, default=5, help="price window around base")
    ap.add_argument("--seed-depth", type=int, default=200, help="initial resting depth on each side")
    ap.add_argument("--seed", type=int, default=None, help="random seed")
    args = ap.parse_args()

    asyncio.run(run_benchmark(
        n=args.n,
        concurrency=args.concurrency,
        symbol=args.symbol,
        base=args.base,
        spread=args.spread,
        seed_depth=args.seed_depth,
        seed=args.seed,
    ))


if __name__ == "__main__":
    main()
