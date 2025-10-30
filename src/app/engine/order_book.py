import asyncio
import logging
import threading
import heapq
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Deque, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
from uuid import uuid4
from datetime import datetime, timezone

# -----------------------------
# Utilities
# -----------------------------

def utc_ts() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def dec(x: Optional[float | int | str | Decimal]) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def d2s(x: Decimal) -> str:
    # Normalize for cleaner JSON strings
    return format(x.normalize(), 'f') if x == x.normalize() else str(x)

# -----------------------------
# Types
# -----------------------------

class Side:
    BUY = "buy"
    SELL = "sell"


class OrderType:
    MARKET = "market"
    LIMIT = "limit"
    IOC = "ioc"
    FOK = "fok"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    price: Optional[Decimal]
    timestamp: str


@dataclass
class Trade:
    trade_id: str
    symbol: str
    price: Decimal
    quantity: Decimal
    aggressor_side: str
    maker_order_id: str
    taker_order_id: str
    timestamp: str


@dataclass
class PriceLevel:
    price: Decimal
    orders: Deque[Order] = field(default_factory=deque)
    total_qty: Decimal = field(default_factory=lambda: Decimal("0"))

    def add(self, order: Order):
        self.orders.append(order)
        self.total_qty += order.quantity

    def peek(self) -> Optional[Order]:
        return self.orders[0] if self.orders else None

    def pop(self) -> Optional[Order]:
        if not self.orders:
            return None
        o = self.orders.popleft()
        self.total_qty -= o.quantity
        return o

    def remove_empty(self) -> bool:
        return not self.orders or self.total_qty <= 0


class OrderBookSide:
    def __init__(self, is_bid: bool):
        self.is_bid = is_bid
        self.levels: Dict[Decimal, PriceLevel] = {}
        # Use a heap for price discovery; store negatives for bids to simulate max-heap
        self.prices_heap: List[Decimal] = []

    def _heap_key(self, price: Decimal) -> Decimal:
        return -price if self.is_bid else price

    def best_price(self) -> Optional[Decimal]:
        # Pop stale prices (levels removed or zero qty)
        while self.prices_heap:
            top = self.prices_heap[0]
            actual = -top if self.is_bid else top
            lvl = self.levels.get(actual)
            if lvl is not None and lvl.total_qty > 0 and lvl.orders:
                return actual
            # stale entry; remove
            heapq.heappop(self.prices_heap)
        return None

    def get_level(self, price: Decimal) -> PriceLevel:
        lvl = self.levels.get(price)
        if lvl is None:
            lvl = PriceLevel(price)
            self.levels[price] = lvl
            heapq.heappush(self.prices_heap, self._heap_key(price))
        return lvl

    def remove_level_if_empty(self, price: Decimal):
        lvl = self.levels.get(price)
        if lvl and (lvl.total_qty <= 0 or not lvl.orders):
            # Lazy removal from heap; best_price will skip stale entries
            del self.levels[price]

    def iter_match_prices(self, limit: Optional[Decimal]) -> List[Decimal]:
        # Build sorted price list on demand from current levels
        prices = [p for p, lvl in self.levels.items() if lvl.total_qty > 0 and lvl.orders]
        if self.is_bid:
            prices.sort(reverse=True)
            return [p for p in prices if (limit is None or p >= limit)]
        else:
            prices.sort()
            return [p for p in prices if (limit is None or p <= limit)]

    def depth(self, depth: int) -> List[Tuple[str, str]]:
        res: List[Tuple[str, str]] = []
        prices = [p for p, lvl in self.levels.items() if lvl.total_qty > 0 and lvl.orders]
        prices.sort(reverse=True if self.is_bid else False)
        for i, p in enumerate(prices):
            if i >= depth:
                break
            lvl = self.levels[p]
            res.append((d2s(p), d2s(lvl.total_qty)))
        return res


class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids = OrderBookSide(is_bid=True)
        self.asks = OrderBookSide(is_bid=False)

    def best_bid(self) -> Optional[Tuple[str, str]]:
        p = self.bids.best_price()
        if p is None:
            return None
        lvl = self.bids.levels[p]
        return (d2s(p), d2s(lvl.total_qty)) if lvl.total_qty > 0 else None

    def best_ask(self) -> Optional[Tuple[str, str]]:
        p = self.asks.best_price()
        if p is None:
            return None
        lvl = self.asks.levels[p]
        return (d2s(p), d2s(lvl.total_qty)) if lvl.total_qty > 0 else None

    def bbo(self) -> Dict:
        return {
            "bid": self.best_bid(),
            "ask": self.best_ask(),
        }

    def depth(self, depth: int = 10) -> Dict[str, List[Tuple[str, str]]]:
        return {
            "bids": self.bids.depth(depth),
            "asks": self.asks.depth(depth),
        }


class PubSub:
    def __init__(self):
        self.marketdata_subs: Dict[str, set] = {}
        self.trade_subs: Dict[str, set] = {}
        self.lock = asyncio.Lock()

    async def subscribe_md(self, symbol: str, ws):
        async with self.lock:
            self.marketdata_subs.setdefault(symbol, set()).add(ws)

    async def unsubscribe_md(self, symbol: str, ws):
        async with self.lock:
            self.marketdata_subs.get(symbol, set()).discard(ws)

    async def subscribe_trades(self, symbol: str, ws):
        async with self.lock:
            self.trade_subs.setdefault(symbol, set()).add(ws)

    async def unsubscribe_trades(self, symbol: str, ws):
        async with self.lock:
            self.trade_subs.get(symbol, set()).discard(ws)

    async def broadcast_md(self, symbol: str, payload: Dict):
        conns = list(self.marketdata_subs.get(symbol, set()))
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                # best-effort
                pass

    async def broadcast_trade(self, symbol: str, payload: Dict):
        conns = list(self.trade_subs.get(symbol, set()))
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                pass


class MatchingEngine:
    def __init__(self, publisher: PubSub):
        self.publisher = publisher
        self.books: Dict[str, OrderBook] = {}
        # Per-symbol locks for thread-safe book updates
        self._locks: Dict[str, threading.Lock] = {}
        # Thread pool for CPU-bound matching
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.logger = logging.getLogger("engine")

    def _book(self, symbol: str) -> OrderBook:
        ob = self.books.get(symbol)
        if ob is None:
            ob = OrderBook(symbol)
            self.books[symbol] = ob
        return ob

    async def submit(self, *, symbol: str, order_type: str, side: str, quantity: Decimal, price: Optional[Decimal]) -> Dict:
        # Validation
        if side not in (Side.BUY, Side.SELL):
            raise ValueError("invalid side")
        if order_type not in (OrderType.MARKET, OrderType.LIMIT, OrderType.IOC, OrderType.FOK):
            raise ValueError("invalid order_type")
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        if order_type in (OrderType.LIMIT, OrderType.IOC, OrderType.FOK) and (price is None or price <= 0):
            raise ValueError("price must be > 0 for limit/IOC/FOK")

        o = Order(
            order_id=str(uuid4()),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=dec(quantity),
            price=dec(price) if price is not None else None,
            timestamp=utc_ts(),
        )

        loop = asyncio.get_running_loop()
        # Execute CPU-bound matching in a thread to allow concurrency across symbols
        status, filled_qty, remaining, trades = await loop.run_in_executor(
            self.executor,
            self._submit_sync,
            o,
        )

        # Publish asynchronously after state mutation (best-effort)
        book = self._book(symbol)
        await self._publish_md(book)
        for t in trades:
            await self._publish_trade(t)

        return {
            "status": status,
            "order_id": o.order_id,
            "filled_quantity": d2s(filled_qty),
            "remaining_quantity": d2s(remaining),
            "trades": [self._trade_to_dict(t) for t in trades],
        }

    def _sym_lock(self, symbol: str) -> threading.Lock:
        # Get or create a per-symbol lock
        lk = self._locks.get(symbol)
        if lk is None:
            lk = threading.Lock()
            self._locks[symbol] = lk
        return lk

    def _submit_sync(self, o: Order) -> Tuple[str, Decimal, Decimal, List[Trade]]:
        # Synchronous core matching, protected by per-symbol lock
        lock = self._sym_lock(o.symbol)
        with lock:
            book = self._book(o.symbol)

            # FOK pre-check
            if o.order_type == OrderType.FOK and not self._can_fulfill_fok(book, o):
                return ("rejected", Decimal("0"), o.quantity, [])

            remaining = o.quantity
            trades = self._match(book, o, remaining)
            filled_qty = sum((t.quantity for t in trades), Decimal("0"))
            remaining = o.quantity - filled_qty

            if remaining > 0 and o.order_type == OrderType.LIMIT:
                self._rest_order(book, Order(
                    order_id=o.order_id,
                    symbol=o.symbol,
                    side=o.side,
                    order_type=o.order_type,
                    quantity=remaining,
                    price=o.price,
                    timestamp=o.timestamp,
                ))
                status = "accepted"
            elif remaining > 0 and o.order_type == OrderType.IOC:
                status = "canceled"
            elif remaining > 0 and o.order_type == OrderType.FOK:
                status = "canceled"
            else:
                status = "filled"

            return (status, filled_qty, remaining, trades)

    def _can_fulfill_fok(self, book: OrderBook, o: Order) -> bool:
        need = o.quantity
        if o.side == Side.BUY:
            # consume asks up to limit price
            limit = o.price if o.order_type != OrderType.MARKET else None
            for p in book.asks.iter_match_prices(limit):
                lvl = book.asks.levels[p]
                if need <= 0:
                    break
                if limit is not None and p > limit:
                    break
                need -= lvl.total_qty
            return need <= 0
        else:
            limit = o.price if o.order_type != OrderType.MARKET else None
            for p in book.bids.iter_match_prices(limit):
                lvl = book.bids.levels[p]
                if need <= 0:
                    break
                if limit is not None and p < limit:
                    break
                need -= lvl.total_qty
            return need <= 0

    def _match(self, book: OrderBook, o: Order, remaining: Decimal) -> List[Trade]:
        trades: List[Trade] = []
        if o.side == Side.BUY:
            # Buy matches against asks from low to high
            while remaining > 0:
                best = book.asks.best_price()
                if best is None:
                    break
                if o.order_type in (OrderType.LIMIT, OrderType.IOC, OrderType.FOK) and o.price is not None and best > o.price:
                    break  # not marketable at or better than limit price
                lvl = book.asks.levels[best]
                while remaining > 0 and lvl.orders:
                    maker = lvl.peek()
                    assert maker is not None
                    trade_qty = min(remaining, maker.quantity)
                    trades.append(self._make_trade(book.symbol, price=best, qty=trade_qty, aggressor=o, maker=maker))
                    remaining -= trade_qty
                    maker.quantity -= trade_qty
                    lvl.total_qty -= trade_qty
                    if maker.quantity <= 0:
                        lvl.pop()
                if lvl.remove_empty():
                    book.asks.remove_level_if_empty(best)
                # continue loop
        else:
            # Sell matches against bids from high to low
            while remaining > 0:
                best = book.bids.best_price()
                if best is None:
                    break
                if o.order_type in (OrderType.LIMIT, OrderType.IOC, OrderType.FOK) and o.price is not None and best < o.price:
                    break
                lvl = book.bids.levels[best]
                while remaining > 0 and lvl.orders:
                    maker = lvl.peek()
                    assert maker is not None
                    trade_qty = min(remaining, maker.quantity)
                    trades.append(self._make_trade(book.symbol, price=best, qty=trade_qty, aggressor=o, maker=maker))
                    remaining -= trade_qty
                    maker.quantity -= trade_qty
                    lvl.total_qty -= trade_qty
                    if maker.quantity <= 0:
                        lvl.pop()
                if lvl.remove_empty():
                    book.bids.remove_level_if_empty(best)
        return trades

    def _rest_order(self, book: OrderBook, order: Order):
        if order.side == Side.BUY:
            lvl = book.bids.get_level(order.price)  # type: ignore[arg-type]
            lvl.add(order)
        else:
            lvl = book.asks.get_level(order.price)  # type: ignore[arg-type]
            lvl.add(order)

    def _make_trade(self, symbol: str, price: Decimal, qty: Decimal, aggressor: Order, maker: Order) -> Trade:
        t = Trade(
            trade_id=str(uuid4()),
            symbol=symbol,
            price=price,
            quantity=qty,
            aggressor_side=aggressor.side,
            maker_order_id=maker.order_id,
            taker_order_id=aggressor.order_id,
            timestamp=utc_ts(),
        )
        self.logger.info({
            "type": "trade",
            "symbol": symbol,
            "price": d2s(price),
            "quantity": d2s(qty),
            "aggressor_side": aggressor.side,
            "maker_order_id": maker.order_id,
            "taker_order_id": aggressor.order_id,
        })
        return t

    def _trade_to_dict(self, t: Trade) -> Dict:
        return {
            "timestamp": t.timestamp,
            "symbol": t.symbol,
            "trade_id": t.trade_id,
            "price": d2s(t.price),
            "quantity": d2s(t.quantity),
            "aggressor_side": t.aggressor_side,
            "maker_order_id": t.maker_order_id,
            "taker_order_id": t.taker_order_id,
        }

    async def _publish_md(self, book: OrderBook):
        payload = {
            "timestamp": utc_ts(),
            "symbol": book.symbol,
            "bbo": book.bbo(),
            "asks": book.depth(10)["asks"],
            "bids": book.depth(10)["bids"],
        }
        await self.publisher.broadcast_md(book.symbol, payload)

    async def _publish_trade(self, t: Trade):
        await self.publisher.broadcast_trade(t.symbol, self._trade_to_dict(t))
