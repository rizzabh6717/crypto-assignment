import logging
import sys
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.engine.order_book import MatchingEngine, PubSub, Side, OrderType, dec

# Configure logging (JSON-like)
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format='%(message)s'
)

pubsub = PubSub()
engine = MatchingEngine(pubsub)
app = FastAPI(title="Crypto Matching Engine", version="0.1.0")


class OrderIn(BaseModel):
    symbol: str = Field(example="BTC-USDT")
    order_type: str = Field(example="limit")  # market, limit, ioc, fok
    side: str = Field(example="buy")  # buy, sell
    quantity: Decimal = Field(gt=0)
    price: Optional[Decimal] = None


@app.post("/orders")
async def submit_order(body: OrderIn):
    try:
        result = await engine.submit(
            symbol=body.symbol,
            order_type=body.order_type,
            side=body.side,
            quantity=dec(body.quantity),
            price=dec(body.price) if body.price is not None else None,
        )
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "internal_error"})


@app.get("/bbo")
async def get_bbo(symbol: str):
    book = engine.books.get(symbol)
    if not book:
        return {"symbol": symbol, "bbo": {"bid": None, "ask": None}}
    return {"symbol": symbol, "bbo": book.bbo()}


@app.get("/depth")
async def get_depth(symbol: str, levels: int = 10):
    book = engine.books.get(symbol)
    if not book:
        return {"symbol": symbol, "asks": [], "bids": []}
    d = book.depth(levels)
    return {"symbol": symbol, **d}


@app.websocket("/ws/marketdata")
async def ws_marketdata(ws: WebSocket, symbol: str = Query(...)):
    await ws.accept()
    await pubsub.subscribe_md(symbol, ws)
    try:
        while True:
            # Keep connection open; we don't expect client messages
            await ws.receive_text()
    except WebSocketDisconnect:
        await pubsub.unsubscribe_md(symbol, ws)
    except Exception:
        await pubsub.unsubscribe_md(symbol, ws)


@app.websocket("/ws/trades")
async def ws_trades(ws: WebSocket, symbol: str = Query(...)):
    await ws.accept()
    await pubsub.subscribe_trades(symbol, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await pubsub.unsubscribe_trades(symbol, ws)
    except Exception:
        await pubsub.unsubscribe_trades(symbol, ws)
