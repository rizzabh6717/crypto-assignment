from decimal import Decimal
import sys
import os

import pytest

# Add project root to path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from app.engine.order_book import MatchingEngine, PubSub, Side, OrderType, dec
import asyncio


@pytest.mark.asyncio
async def test_price_time_priority_fifo():
    eng = MatchingEngine(PubSub())
    symbol = "BTC-USDT"

    # Add two sell limits at same price, FIFO order
    r1 = await eng.submit(symbol=symbol, order_type=OrderType.LIMIT, side=Side.SELL, quantity=dec("1.0"), price=dec("100"))
    r2 = await eng.submit(symbol=symbol, order_type=OrderType.LIMIT, side=Side.SELL, quantity=dec("1.0"), price=dec("100"))

    # Aggressive buy that takes from price 100
    r3 = await eng.submit(symbol=symbol, order_type=OrderType.MARKET, side=Side.BUY, quantity=dec("1.5"), price=None)

    # First maker should be fully filled, second partially
    assert r3["status"] in ("filled", "accepted", "canceled")
    trades = r3["trades"]
    assert trades[0]["maker_order_id"] != trades[-1]["maker_order_id"]


@pytest.mark.asyncio
async def test_ioc_does_not_rest():
    eng = MatchingEngine(PubSub())
    symbol = "BTC-USDT"

    # Rest sell at 101
    await eng.submit(symbol=symbol, order_type=OrderType.LIMIT, side=Side.SELL, quantity=dec("1"), price=dec("101"))

    # IOC buy at 100 (not marketable) should cancel entirely and not rest
    r = await eng.submit(symbol=symbol, order_type=OrderType.IOC, side=Side.BUY, quantity=dec("1"), price=dec("100"))
    assert r["status"] == "canceled"
    # Book unchanged
    book = eng.books[symbol]
    assert len(book.asks.levels[Decimal("101")].orders) == 1


@pytest.mark.asyncio
async def test_fok_all_or_none():
    eng = MatchingEngine(PubSub())
    symbol = "BTC-USDT"

    # Two asks at 100, totaling 1.5
    await eng.submit(symbol=symbol, order_type=OrderType.LIMIT, side=Side.SELL, quantity=dec("1.0"), price=dec("100"))
    await eng.submit(symbol=symbol, order_type=OrderType.LIMIT, side=Side.SELL, quantity=dec("0.5"), price=dec("100"))

    # FOK buy 2.0 at 100 should reject
    r = await eng.submit(symbol=symbol, order_type=OrderType.FOK, side=Side.BUY, quantity=dec("2.0"), price=dec("100"))
    assert r["status"] == "rejected"

    # FOK buy 1.5 at 100 should fill completely
    r2 = await eng.submit(symbol=symbol, order_type=OrderType.FOK, side=Side.BUY, quantity=dec("1.5"), price=dec("100"))
    assert r2["status"] in ("filled", "accepted")
    assert r2["remaining_quantity"] == "0"


@pytest.mark.asyncio
async def test_market_order_trade_through_protection():
    eng = MatchingEngine(PubSub())
    symbol = "BTC-USDT"

    # Resting sell orders at different prices: 1.0 @ 101, 1.0 @ 100
    await eng.submit(symbol=symbol, order_type=OrderType.LIMIT, side=Side.SELL, quantity=dec("1.0"), price=dec("101"))
    await eng.submit(symbol=symbol, order_type=OrderType.LIMIT, side=Side.SELL, quantity=dec("1.0"), price=dec("100"))

    # Market buy order to take both
    r = await eng.submit(symbol=symbol, order_type=OrderType.MARKET, side=Side.BUY, quantity=dec("1.5"), price=None)

    assert r["status"] in ("filled", "accepted")
    trades = r["trades"]
    assert len(trades) == 2

    # Verify that the first trade was at the best price (100)
    assert trades[0]["price"] == "100"
    assert trades[0]["quantity"] == "1"

    # Verify that the second trade was at the next price level (101)
    assert trades[1]["price"] == "101"
    assert trades[1]["quantity"] == "0.5"
