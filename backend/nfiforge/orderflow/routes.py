# /api/orderflow/...: footprint bars for a bot's pair (asking for a pair is what makes the worker record it), the
# worker's health and what each exchange can supply. reads the worker's database, read-only

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException

from nfiforge.orderflow import sources
from nfiforge.orderflow.db import OrderflowDb
from nfiforge.workerproc import WorkerProcess, read_json

TF = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
MAX_BARS = 1500
LOOK_S = 600  # a pair the page stopped asking for is dropped after this


class Orderflow(WorkerProcess):
  def __init__(
    self, folder: Path, memory_mb: int, settings: dict, open_pairs: Callable[[], list[dict]], defaults: dict
  ):
    super().__init__("orderflow", "nfiforge.orderflow.worker", folder, memory_mb)
    self.settings, self.open_pairs = settings, open_pairs
    self.defaults = defaults  # config.yaml's options, which the settings page's reset goes back to
    self.looked: dict[tuple[str, str, str], float] = {}  # pairs the page asked for -> last time
    self.db = OrderflowDb(folder / "orderflow.db", readonly=True)

  async def start(self) -> None:
    await super().start()
    self.share("settings.json", lambda: self.settings, every=30)
    self.share("watch.json", self.watch, every=2)

  def look(self, exchange: str, market: str, symbol: str) -> None:
    self.looked[(exchange, market, symbol)] = time.time()

  def watch(self) -> dict:
    # pairs on screen first (newest look first), then open trades; the worker takes the first max_pairs
    now = time.time()
    self.looked = {key: seen_at for key, seen_at in self.looked.items() if now - seen_at < LOOK_S}
    pairs = [
      {"exchange": exchange, "market": market, "symbol": symbol}
      for (exchange, market, symbol), _ in sorted(self.looked.items(), key=lambda item: -item[1])
    ]
    if self.settings.get("watch_open_trades", True):
      pairs += [pair for pair in self.open_pairs() if pair not in pairs]
    return {"pairs": pairs}

  def status(self) -> dict:
    return (
      {"memory_mb": self.memory_mb, "settings": self.settings, "defaults": self.defaults}
      | self.state
      | {"worker": read_json(self.folder / "status.json")}
    )


def router(orderflow: Orderflow, bot_market: Callable[[str], tuple[str, str]]) -> APIRouter:
  api = APIRouter(prefix="/api/orderflow")

  @api.get("/status")
  async def status():
    return orderflow.status()

  @api.get("/sources")
  async def exchange_sources():
    return sources.sources_table()

  @api.get("/bars")
  async def bars(
    bot: str, pair: str, tf: str = "5m", start: float = 0, end: float = 0, rows: int = 1, market: str = ""
  ):
    # footprint bars of tf over [start, end) (seconds; default the latest MAX_BARS bars), price rows merged `rows` at
    # a time. asking marks the pair as watched; until the worker has it, the answer says so. market: "spot" reads
    # the spot pair on the bot's exchange (spot vs perp delta), default the bot's own market
    if tf not in TF:
      raise HTTPException(400, f"timeframe must be one of {', '.join(TF)}")
    if market not in ("", "spot", "swap"):
      raise HTTPException(400, "market must be spot or swap")
    exchange, bot_mkt = bot_market(bot)
    market = market or bot_mkt
    orderflow.look(exchange, market, pair)
    seconds = TF[tf]
    end = end or time.time() + seconds
    start = max(start or end - seconds * MAX_BARS, end - seconds * MAX_BARS)
    symbol = await asyncio.to_thread(orderflow.db.symbol, exchange, market, pair)
    if symbol is None:
      return {"pending": True, "exchange": exchange, "market": market, "bars": [], "big": [], "cover": []}
    rows = max(1, min(rows, 1000))
    data = await asyncio.to_thread(
      orderflow.db.read, symbol["id"], seconds * 1000, int(start * 1000), int(end * 1000), rows
    )
    cover = await asyncio.to_thread(orderflow.db.covered, symbol["id"])
    return data | {
      "pending": False,
      "exchange": exchange,
      "market": market,
      "step": symbol["step"] * rows,
      "big_usd": symbol["big_usd"],
      "cover": [{"start": span_start, "end": span_end, "source": source} for span_start, span_end, source in cover],
    }

  async def _sym(bot: str, pair: str) -> dict | None:
    exchange, market = bot_market(bot)
    orderflow.look(exchange, market, pair)
    return await asyncio.to_thread(orderflow.db.symbol, exchange, market, pair)

  @api.get("/heat")
  async def heat(
    bot: str, pair: str, tf: str = "5m", start: float = 0, end: float = 0, per_bar: int = 4, rows: int = 1
  ):
    # the recorded book over [start, end) (seconds): heatmap columns (per_bar per bar, rows merged), imbalance per
    # bar, large-order events. at most 400 bars
    if tf not in TF:
      raise HTTPException(400, f"timeframe must be one of {', '.join(TF)}")
    seconds = TF[tf]
    end = end or time.time() + seconds
    start = max(start or end - seconds * 200, end - seconds * 400)
    symbol = await _sym(bot, pair)
    if symbol is None:
      return {"cols": [], "imb": [], "events": [], "cover": []}
    per_bar, rows = max(1, min(per_bar, 60)), max(1, min(rows, 1000))
    data = await asyncio.to_thread(
      orderflow.db.heat, symbol["id"], seconds * 1000, int(start * 1000), int(end * 1000), per_bar, rows
    )
    cover = await asyncio.to_thread(orderflow.db.covered, symbol["id"], "book_cover")
    live = await asyncio.to_thread(read_json, orderflow.folder / "live" / f"{symbol['id']}.json")
    return data | {
      "step": symbol["step"] * rows,
      "wall_usd": (live or {}).get("wall_usd", 0),
      "cover": [{"start": span_start, "end": span_end, "source": source} for span_start, span_end, source in cover],
    }

  @api.get("/book")
  async def book_now(bot: str, pair: str):
    # the latest book sample (dom, depth chart) and what traded per price row today (utc), at the stored row size
    symbol = await _sym(bot, pair)
    if symbol is None:
      return {"pending": True}
    live = await asyncio.to_thread(read_json, orderflow.folder / "live" / f"{symbol['id']}.json")
    now = time.time()
    day = int((now - now % 86400) * 1000)
    traded = await asyncio.to_thread(orderflow.db.traded, symbol["id"], day)
    tape = await asyncio.to_thread(read_json, orderflow.folder / "live" / f"{symbol['id']}.tape.json")
    return {
      "pending": False,
      "book": live,
      "step": symbol["step"],
      "traded": traded,
      "last": ((tape or {}).get("trades") or [None])[-1],  # the latest trade: [ms, price, amount, taker bought]
      "stale": not live or now * 1000 - live["ts"] > 10_000,
    }

  @api.get("/derivs")
  async def derivatives(bot: str, pair: str, tf: str = "5m", start: float = 0, end: float = 0):
    # perpetuals, per bar of tf over [start, end) (seconds; default as /bars): open interest (base), liquidated longs /
    # shorts (value, count), settled funding rates
    if tf not in TF:
      raise HTTPException(400, f"timeframe must be one of {', '.join(TF)}")
    seconds = TF[tf]
    end = end or time.time() + seconds
    start = max(start or end - seconds * MAX_BARS, end - seconds * MAX_BARS)
    symbol = await _sym(bot, pair)
    if symbol is None:
      return {"oi": [], "liq": [], "funding": []}
    return await asyncio.to_thread(
      orderflow.db.derivs, symbol["id"], seconds * 1000, int(start * 1000), int(end * 1000)
    )

  @api.get("/tape")
  async def tape(bot: str, pair: str):
    # the latest recorded trades (time & sales), oldest first: [ms, price, amount, taker bought]
    symbol = await _sym(bot, pair)
    if symbol is None:
      return {"pending": True}
    live = await asyncio.to_thread(read_json, orderflow.folder / "live" / f"{symbol['id']}.tape.json")
    return {
      "pending": False,
      "trades": (live or {}).get("trades", []),
      "big_usd": symbol["big_usd"],
      "step": symbol["step"],
    }

  return api
