# public exchange candles for charts of older trades (the bot itself only keeps a few days); no api keys

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

import ccxt.async_support as ccxt

# candle size picked from the span so a chart stays around 1000 candles or less
STEPS = [(2 * 86400, "5m", 300), (8 * 86400, "15m", 900), (40 * 86400, "1h", 3600), (160 * 86400, "4h", 14400)]
# a timeframe picked by hand: its candle size, and the most candles one chart fetches (the newest part is kept)
TF_SEC = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
MAX_CANDLES = 5000


def pick_timeframe(span_s: float) -> tuple[str, int]:
  for limit, timeframe, seconds in STEPS:
    if span_s <= limit:
      return timeframe, seconds
  return "1d", 86400


class CandleSource:
  def __init__(self, cache_size: int = 64) -> None:
    self._ex: dict[tuple[str, str], ccxt.Exchange] = {}
    self._cache: OrderedDict[tuple, list] = OrderedDict()
    self._size = cache_size
    self._tickers: dict[tuple, dict] = {}
    self._lock = asyncio.Lock()

  def _exchange(self, name: str, futures: bool) -> ccxt.Exchange:
    key = (name, "swap" if futures else "spot")
    if key not in self._ex:
      cls = getattr(ccxt, name, None)
      if cls is None:
        raise ValueError(f"ccxt has no exchange called {name}")
      self._ex[key] = cls({"enableRateLimit": True, "options": {"defaultType": key[1]}})
    return self._ex[key]

  async def close(self) -> None:
    await asyncio.gather(*(e.close() for e in self._ex.values()), return_exceptions=True)

  async def candles(
    self, exchange: str, futures: bool, pair: str, start: float, end: float, timeframe: str | None = None
  ) -> dict:
    # pad the trade window so the move before entry and after exit shows
    pad = max((end - start) * 0.25, 3 * 3600)
    start, end = start - pad, min(end + pad, time.time())
    clipped = False
    if timeframe:
      seconds = TF_SEC[timeframe]
      if (end - start) / seconds > MAX_CANDLES:
        start, clipped = end - MAX_CANDLES * seconds, True
    else:
      timeframe, seconds = pick_timeframe(end - start)
    # round to candle buckets so nearby requests share a cache entry; open trades refresh each candle
    key = (exchange, futures, pair, timeframe, int(start // seconds), int(end // seconds))
    if key in self._cache:
      self._cache.move_to_end(key)
      return {"timeframe": timeframe, "candles": self._cache[key], "clipped": clipped}
    async with self._lock:  # one fetch at a time keeps us well inside exchange rate limits
      out = await self._range(self._exchange(exchange, futures), pair, timeframe, seconds, start, end)
    self._cache[key] = out
    if len(self._cache) > self._size:
      self._cache.popitem(last=False)
    return {"timeframe": timeframe, "candles": out, "clipped": clipped}

  async def _range(
    self, exchange: ccxt.Exchange, pair: str, timeframe: str, seconds: int, start: float, end: float
  ) -> list:
    since, out = int(start * 1000), []
    while since < end * 1000:
      batch = await exchange.fetch_ohlcv(pair, timeframe, since=since, limit=1000)
      if not batch:
        break
      out += [candle for candle in batch if candle[0] <= end * 1000]
      if batch[-1][0] + seconds * 1000 <= since:
        break
      since = batch[-1][0] + seconds * 1000
      if len(batch) < 2:
        break
    return out

  # one closed trade's own life from the candle it opened in, not cached (each trade is measured once); 1m up to 16 h so
  # short trades are measured closely: (timeframe, seconds per candle, candles)
  async def trade_candles(
    self, exchange: str, futures: bool, pair: str, start: float, end: float
  ) -> tuple[str, int, list]:
    timeframe, seconds = ("1m", 60) if end - start <= 16 * 3600 else pick_timeframe(end - start)
    async with self._lock:
      return (
        timeframe,
        seconds,
        await self._range(self._exchange(exchange, futures), pair, timeframe, seconds, start // seconds * seconds, end),
      )

  async def latest(self, exchange: str, futures: bool, pair: str, timeframe: str, limit: int) -> dict:
    # newest `limit` candles of one timeframe; cached for a minute
    key = (exchange, futures, pair, timeframe, limit, int(time.time() // 60))
    if key in self._cache:
      self._cache.move_to_end(key)
      return {"timeframe": timeframe, "candles": self._cache[key]}
    async with self._lock:
      out = await self._exchange(exchange, futures).fetch_ohlcv(pair, timeframe, limit=limit)
    self._cache[key] = out
    if len(self._cache) > self._size:
      self._cache.popitem(last=False)
    return {"timeframe": timeframe, "candles": out}

  async def ticker(self, exchange: str, futures: bool, pair: str) -> dict:
    # live price for the trade forms; cached 2 s so several open forms share one request
    slot = int(time.time() // 2)
    key = (exchange, futures, pair, slot)
    if key in self._tickers:
      return self._tickers[key]
    ticker = await self._exchange(exchange, futures).fetch_ticker(pair)
    out = {
      "last": ticker.get("last"),
      "bid": ticker.get("bid"),
      "ask": ticker.get("ask"),
      "ts": (ticker.get("timestamp") or time.time() * 1000) / 1000,
    }
    # a separate cache (not the candles'): a form asking every 2 s would push chart candles out
    self._tickers = {cache_key: value for cache_key, value in self._tickers.items() if cache_key[3] == slot}
    self._tickers[key] = out
    return out
