# the order flow worker process: records the trade stream of every watched pair into one-minute footprint rows and
# fills history back from the exchange's archives / api, one fill at a time. reads watch.json + settings.json
# (written by the dashboard), writes orderflow.db + status.json. run by nfiforge.orderflow.supervisor

from __future__ import annotations

import argparse
import asyncio
import contextlib
import heapq
import json
import logging
import os
import shutil
import signal
import tempfile
import time
from collections import deque
from pathlib import Path

import httpx

from nfiforge.orderflow import book, derivs, sources
from nfiforge.orderflow.aggregate import MINUTE, Minutes, Trade, big_size, pick_step
from nfiforge.orderflow.db import OrderflowDb, key

log = logging.getLogger("orderflow")

DEFAULTS = {
  "history_days": 3,
  "retention_days": 30,
  "max_pairs": 10,
  "book": True,
  "book_history_days": 0,
  "book_retention_days": 7,
  "big_pct": 0.5,
  "big_usd": 0,
}
WRITE_EVERY = 1.0  # s between writes of the live open minute
TAPE_N = 500  # latest trades kept for the time & sales tape
BIG_N = 20_000  # latest trade values the big-trade size is read from
BIG_EVERY = 600  # s between big-trade size updates
RETRY_MISSING = 6 * 3600  # s before an archive file that wasn't there is asked for again


def read_json(path: Path, default):
  try:
    return json.loads(path.read_text())
  except (OSError, ValueError):
    return default


def ceil_minute(timestamp_ms: float) -> int:
  return int(-(-timestamp_ms // MINUTE) * MINUTE)


def missing(covered: list[tuple[int, int, str]], start: int, end: int) -> list[tuple[int, int]]:
  # parts of [start, end) not covered yet, newest first
  gaps, cursor = [], start
  for span_start, span_end, _ in covered:
    if span_end <= cursor:
      continue
    if span_start >= end:
      break
    if span_start > cursor:
      gaps.append((cursor, min(span_start, end)))
    cursor = max(cursor, span_end)
  if cursor < end:
    gaps.append((cursor, end))
  return gaps[::-1]


class Exchanges:
  # one ccxt pro client per exchange + market type, shared by every pair on it
  def __init__(self) -> None:
    self.clients: dict[tuple[str, str], object] = {}
    self.loaded: dict[tuple[str, str], asyncio.Lock] = {}

  async def get(self, exchange: str, market: str):
    client_key = (exchange, market)
    if client_key not in self.clients:
      self.clients[client_key] = sources.make_exchange(exchange, market)
      self.loaded[client_key] = asyncio.Lock()
    client = self.clients[client_key]
    async with self.loaded[client_key]:
      if not client.markets:
        await client.load_markets()
    return client

  async def close(self) -> None:
    await asyncio.gather(*(client.close() for client in self.clients.values()), return_exceptions=True)


class Pair:
  def __init__(self, worker: Worker, exchange: str, market: str, symbol: str) -> None:
    self.w, self.exchange, self.market, self.symbol = worker, exchange, market, symbol
    self.key = key(exchange, market, symbol)
    self.status: dict = {
      "exchange": exchange,
      "market": market,
      "symbol": symbol,
      "live": "starting",
      "fill": "waiting",
    }
    self.tasks: list[asyncio.Task] = []
    self.trades_n = 0
    self.missing: dict[str, float] = {}  # archive url -> when it wasn't there
    self.traded: dict[float, float] = {}  # price -> amount traded since the last book sample (fills vs pulls)
    self.book_on = False  # a book sampler runs for this pair (it alone empties traded)
    self.ob: dict | None = None  # the latest book from the stream
    self.tape: deque = deque(maxlen=TAPE_N)  # latest trades (ms, price, amount, taker bought), newest last
    self.values: deque = deque(maxlen=BIG_N)  # latest trade values (USD), for the big-trade size

  async def start(self) -> None:
    self.tasks.append(asyncio.create_task(self._run(), name=f"pair {self.key}"))

  async def stop(self) -> None:
    for task in self.tasks:
      task.cancel()
    await asyncio.gather(*self.tasks, return_exceptions=True)

  async def _setup(self) -> tuple[object, dict, dict, float]:
    client = await self.w.exchanges.get(self.exchange, self.market)
    market_info = client.market(self.symbol)
    contract = float(market_info.get("contractSize") or 1.0)
    row = self.w.db.symbol(self.exchange, self.market, self.symbol)
    if row is None:
      # price row size from the tick and price, big trade = top 0.5 % of recent trades by value (at least $1k);
      # both stay fixed for the pair so stored history never needs redoing
      try:
        recent = await client.fetch_trades(self.symbol, limit=1000)
      except sources.ccxtpro.ExchangeError:  # no public trade list (hyperliquid)
        recent = []
      price = float(recent[-1]["price"]) if recent else float((await client.fetch_ticker(self.symbol))["last"])
      tick = float(market_info["precision"]["price"])
      if client.precisionMode != 4:  # 4 = TICK_SIZE; else the precision is a number of decimals
        tick = 10.0**-tick
      values = [float(trade["price"]) * float(trade["amount"]) * contract for trade in recent]
      big = big_size(values, self.w.settings["big_pct"], self.w.settings["big_usd"]) or 1000.0
      row = await asyncio.to_thread(
        self.w.db.add_symbol, self.exchange, self.market, self.symbol, pick_step(price, tick), big
      )
    return client, market_info, row, contract

  async def _run(self) -> None:
    attempt = 0
    while True:
      try:
        client, market_info, row, contract = await self._setup()
        break
      except asyncio.CancelledError:
        raise
      except Exception as e:
        attempt += 1
        self.status.update(live=f"error: {type(e).__name__}: {str(e)[:200]}")
        log.warning(f"{self.key}: {type(e).__name__}: {e}")
        await asyncio.sleep(min(300, 5 * 2**attempt))
    self.status.update(step=row["step"], big_usd=row["big_usd"])
    self.live_start = ceil_minute(time.time() * 1000)
    self.tasks += [
      asyncio.create_task(self._live(client, row, contract)),
      asyncio.create_task(self._fill(client, market_info, row, contract)),
    ]
    if self.w.settings["book"]:
      self.book_on = True
      self.tasks.append(asyncio.create_task(self._book(client, row, contract)))
    if self.market == "swap":
      self.tasks += [
        asyncio.create_task(self._derivs(client, row, contract)),
        asyncio.create_task(self._liqs(client, row, contract)),
      ]

  # ---------------------------------------------------------------------------
  # live: the trade stream from the first whole minute after (re)connecting
  # ---------------------------------------------------------------------------
  async def _live(self, client, row: dict, contract: float) -> None:
    symbol_id, attempt = row["id"], 0
    live = self.w.folder / "live"
    live.mkdir(exist_ok=True)
    while True:
      start = self.live_start = max(self.live_start, ceil_minute(time.time() * 1000))
      mins = Minutes(row["step"], row["big_usd"])
      last_write, last_t, last_big = 0.0, None, time.monotonic()
      self.status.update(live="on", live_since=start)
      try:
        while True:
          batch = await client.watch_trades(self.symbol)
          attempt = 0
          trades = sorted(
            (sources.to_trade(trade, contract) for trade in batch if trade["timestamp"] >= start),
            key=lambda item: item[0],
          )
          self.trades_n += len(trades)
          mins.add(trades)
          if self.book_on:  # only the book sampler reads and resets it
            for _, price, qty, _ in trades:
              self.traded[price] = self.traded.get(price, 0.0) + qty
          self.tape.extend(trades)
          self.values.extend(trade_price * trade_qty for _, trade_price, trade_qty, _ in trades)
          now = time.monotonic()
          if now - last_write >= WRITE_EVERY:
            last_write = now
            bars, levels, big = mins.take()
            open_bars, open_levels, open_big = mins.peek()
            await asyncio.to_thread(self.w.db.write, symbol_id, bars + open_bars, levels + open_levels, big + open_big)
            if bars:
              last_t = bars[-1][0] + MINUTE
              await asyncio.to_thread(self.w.db.add_cover, symbol_id, start, last_t, "live")
            self.status["live_to"] = last_t
            tmp_path = live / f".{symbol_id}.tape.json.tmp"
            tmp_path.write_text(json.dumps({"ts": int(time.time() * 1000), "trades": list(self.tape)}))
            os.replace(tmp_path, live / f"{symbol_id}.tape.json")
          if now - last_big >= BIG_EVERY:
            # the big-trade size follows the pair's recent trading (or the settings' fixed size)
            last_big = now
            big = big_size(list(self.values), self.w.settings["big_pct"], self.w.settings["big_usd"])
            if big and abs(big - row["big_usd"]) > 0.05 * row["big_usd"]:
              row["big_usd"] = mins.big_usd = big
              self.status["big_usd"] = round(big)
              await asyncio.to_thread(self.w.db.set_big, symbol_id, big)
      except asyncio.CancelledError:
        raise
      except Exception as e:
        # the open minute is lost (it may miss trades): the next segment starts at the next whole minute
        attempt += 1
        self.status.update(live=f"reconnecting: {type(e).__name__}: {str(e)[:150]}")
        log.warning(f"{self.key} live: {type(e).__name__}: {e}")
        await asyncio.sleep(min(60, 2**attempt))

  # ---------------------------------------------------------------------------
  # book: the stream keeps self.ob fresh; once a second a sample feeds the large-order tracker and the dom file,
  # every COLUMN_MS one becomes a heatmap column + imbalance row
  # ---------------------------------------------------------------------------
  async def _book_feed(self, client) -> None:
    limit = book.book_limit(sources.ccxt_id(self.exchange), self.market)
    while True:
      try:
        self.ob = await client.watch_order_book(self.symbol, limit)
      except sources.ccxtpro.BadRequest:
        if limit is None:
          raise
        limit = None  # that depth refused: the exchange's default

  async def _book(self, client, row: dict, contract: float) -> None:
    symbol_id, attempt = row["id"], 0
    live = self.w.folder / "live"
    live.mkdir(exist_ok=True)
    while True:
      self.ob, walls = None, None
      feed = asyncio.create_task(self._book_feed(client))
      seg = next_ms = None
      try:
        while True:
          await asyncio.sleep(1)
          if feed.done():
            feed.result()  # raises what stopped it
          order_book = self.ob
          if not order_book or not order_book["bids"] or not order_book["asks"]:
            continue
          now = int(time.time() * 1000)
          bids = [(price, qty * contract) for price, qty, *_ in order_book["bids"] if price > 0]
          asks = [(price, qty * contract) for price, qty, *_ in order_book["asks"] if price > 0]
          if not bids or not asks:
            continue
          traded, self.traded = self.traded, {}
          if walls is None:
            walls = book.Walls(book.wall_usd(bids, asks, row["big_usd"]))
            self.status["wall_usd"] = round(walls.usd)
          events = walls.update(now, bids, asks, traded)
          dom = {"ts": now, "bids": bids[:300], "asks": asks[:300], "wall_usd": walls.usd, "step": row["step"]}
          tmp_path = live / f".{symbol_id}.json.tmp"
          tmp_path.write_text(json.dumps(dom))
          os.replace(tmp_path, live / f"{symbol_id}.json")
          if next_ms is None:
            seg = next_ms = now - now % book.COLUMN_MS + book.COLUMN_MS
          cols, imbalance = [], []
          if now >= next_ms:
            col = book.column(bids, asks, row["step"])
            if col:
              cols.append((next_ms, book.encode(*col)))
              imbalance.append((next_ms, *book.bands(bids, asks)))
            next_ms += book.COLUMN_MS * ((now - next_ms) // book.COLUMN_MS + 1)
          if cols or events:
            await asyncio.to_thread(self.w.db.write_book, symbol_id, cols, imbalance, events)
          if cols:
            await asyncio.to_thread(
              self.w.db.add_cover, symbol_id, seg, cols[-1][0] + book.COLUMN_MS, "live", "book_cover"
            )
          self.status.update(book="on", book_levels=f"{len(bids)}/{len(asks)}")
          attempt = 0
      except asyncio.CancelledError:
        feed.cancel()
        raise
      except Exception as e:
        feed.cancel()
        attempt += 1
        self.status["book"] = f"reconnecting: {type(e).__name__}: {str(e)[:150]}"
        log.warning(f"{self.key} book: {type(e).__name__}: {e}")
        await asyncio.sleep(min(60, 2**attempt))

  # ---------------------------------------------------------------------------
  # perpetuals: open interest each minute (history first, where kept) and funding; liquidations as they come
  # ---------------------------------------------------------------------------
  async def _derivs(self, client, row: dict, contract: float) -> None:
    symbol_id, attempt, rounds = row["id"], 0, 0
    has_hist = derivs.can(client, "fetchOpenInterestHistory")
    self.status["oi"] = (
      "history + live" if has_hist else "live only" if derivs.can(client, "fetchOpenInterest") else "not offered"
    )
    while True:
      try:
        start = int(time.time() * 1000) - self.w.settings["history_days"] * sources.DAY
        open_interest = []
        if has_hist:
          last = await asyncio.to_thread(self.w.db.last_ts, symbol_id, "oi")
          open_interest = await derivs.oi_history(client, self.symbol, max(start, (last or 0) + 1), contract)
        now = await derivs.oi_now(client, self.symbol, contract)
        if now:  # stamped with our clock: some exchanges date it to their last 5 min / 1 h point
          now_ms = int(time.time() * 1000)
          open_interest.append((now_ms - now_ms % MINUTE, now[1]))
        fund = []
        if rounds % 10 == 0:  # settled rates change every few hours
          last = await asyncio.to_thread(self.w.db.last_ts, symbol_id, "funding")
          fund = await derivs.funding_history(client, self.symbol, max(start, (last or 0) + 1))
          self.status["funding"] = await derivs.funding_now(client, self.symbol)
        await asyncio.to_thread(self.w.db.write_derivs, symbol_id, open_interest, fund)
        rounds, attempt = rounds + 1, 0
        self.status.pop("derivs_error", None)
        await asyncio.sleep(60)
      except asyncio.CancelledError:
        raise
      except Exception as e:
        attempt += 1
        self.status["derivs_error"] = f"{type(e).__name__}: {str(e)[:150]}"
        log.warning(f"{self.key} derivs: {type(e).__name__}: {e}")
        await asyncio.sleep(min(600, 30 * 2**attempt))

  async def _liqs(self, client, row: dict, contract: float) -> None:
    symbol_id, attempt = row["id"], 0
    stream = derivs.can(client, "watchLiquidations")
    if not stream and not derivs.can(client, "fetchLiquidations"):
      self.status["liq"] = "not offered"
      return
    self.status.update(liq="stream" if stream else "every 30 s", liq_since=int(time.time() * 1000))
    while True:
      try:
        if stream:
          got = await client.watch_liquidations(self.symbol)
        else:
          last = await asyncio.to_thread(self.w.db.last_ts, symbol_id, "liqs") or self.status["liq_since"]
          got = [
            liq
            for liq in await client.fetch_liquidations(self.symbol, since=last + 1, limit=100)
            if liq["timestamp"] > last
          ]
        rows = derivs.liq_rows(client.id, got, contract)
        if rows:
          await asyncio.to_thread(self.w.db.write_derivs, symbol_id, (), (), rows)
        attempt = 0
        if not stream:
          await asyncio.sleep(30)
      except asyncio.CancelledError:
        raise
      except Exception as e:
        attempt += 1
        self.status["liq"] = f"reconnecting: {type(e).__name__}: {str(e)[:150]}"
        log.warning(f"{self.key} liquidations: {type(e).__name__}: {e}")
        await asyncio.sleep(min(300, 5 * 2**attempt))
        self.status["liq"] = "stream" if stream else "every 30 s"

  # ---------------------------------------------------------------------------
  # history: archives first, then the rest api, newest gap first; one pair fills at a time
  # ---------------------------------------------------------------------------
  async def _fill(self, client, market_info: dict, row: dict, contract: float) -> None:
    symbol_id = row["id"]
    while True:
      try:
        start = int(time.time() * 1000) - self.w.settings["history_days"] * sources.DAY
        start -= start % MINUTE
        gaps = missing(await asyncio.to_thread(self.w.db.covered, symbol_id), start, self.live_start)
        if gaps:
          async with self.w.fill_lock:
            for gap_start, gap_end in gaps:
              await self._fill_gap(client, market_info, row, contract, gap_start, gap_end)
        left = missing(await asyncio.to_thread(self.w.db.covered, symbol_id), start, self.live_start)
        self.status.update(fill="done" if not left else "as far as the exchange allows", fill_error=None)
        if self.w.settings["book"] and self.w.settings["book_history_days"] > 0:
          async with self.w.fill_lock:
            await self._fill_book(market_info, row, contract)
      except asyncio.CancelledError:
        raise
      except Exception as e:  # network trouble: try again next round
        self.status.update(fill="waiting to retry", fill_error=f"{type(e).__name__}: {str(e)[:200]}")
        log.warning(f"{self.key} fill: {type(e).__name__}: {e}")
      self.status["cover"] = await asyncio.to_thread(self.w.db.covered, symbol_id)
      await asyncio.sleep(600)  # new archive files appear once a day; settings may have changed

  async def _fill_gap(
    self, client, market_info: dict, row: dict, contract: float, gap_start: int, gap_end: int
  ) -> None:
    symbol_id = row["id"]
    # archive units, newest first
    for unit in sources.archive_units(self.exchange, self.market, market_info["id"], gap_start, gap_end):
      if time.time() - self.missing.get(unit.urls[0], 0) < RETRY_MISSING:
        continue
      range_start, range_end = max(gap_start, unit.start), min(gap_end, unit.end)
      self.status["fill"] = f"archive {time.strftime('%Y-%m-%d %H:%M', time.gmtime(range_start / 1000))} UTC"
      tmp_dir = Path(tempfile.mkdtemp(dir=self.w.folder / "tmp"))
      try:
        files = await sources.fetch_unit(self.w.http, unit, tmp_dir)
        if files is None:
          self.missing[unit.urls[0]] = time.time()
          continue
        await asyncio.to_thread(
          self._write_range, symbol_id, row, sources.unit_trades(files, unit, contract), range_start, range_end
        )
        await asyncio.to_thread(self.w.db.add_cover, symbol_id, range_start, range_end, "archive")
      finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    # what the archives didn't have: the rest api, gap by gap, newest first
    for rest_start, rest_end in missing(await asyncio.to_thread(self.w.db.covered, symbol_id), gap_start, gap_end):
      self.status["fill"] = f"api {time.strftime('%Y-%m-%d %H:%M', time.gmtime(rest_start / 1000))} UTC"
      range_start, range_end, trades = await sources.rest_trades(client, self.symbol, rest_start, rest_end, contract)
      if range_start < range_end:
        range_start, range_end = ceil_minute(range_start), range_end - range_end % MINUTE
        await asyncio.to_thread(self._write_range, symbol_id, row, trades, range_start, range_end)
        await asyncio.to_thread(self.w.db.add_cover, symbol_id, range_start, range_end, "api")

  async def _fill_book(self, market_info: dict, row: dict, contract: float) -> None:
    # book archives (heavy, off unless book_history_days > 0): bybit daily and gate hourly full books -> heatmap
    # columns + imbalance; binance daily depth bands -> imbalance only
    symbol_id, exchange_id = row["id"], sources.ccxt_id(self.exchange)
    now = int(time.time() * 1000)
    start = now - self.w.settings["book_history_days"] * sources.DAY
    end = min(now - now % sources.DAY, self.live_start)  # archives end at yesterday
    if exchange_id == "binance" and self.market == "swap":
      day = end - sources.DAY
      while day >= start - start % sources.DAY:
        url = book.binance_depth_url(market_info["id"], day)
        if url not in self.missing and not await asyncio.to_thread(
          self.w.db.has_imb, symbol_id, day, day + sources.DAY
        ):
          self.status["fill"] = f"book bands {time.strftime('%Y-%m-%d', time.gmtime(day / 1000))}"
          await self._book_file(url, lambda path: self._write_bands(symbol_id, path))
        day -= sources.DAY
      return
    if exchange_id not in ("bybit", "gate"):
      return
    unit = sources.DAY if exchange_id == "bybit" else 3_600_000
    for gap_start, gap_end in missing(await asyncio.to_thread(self.w.db.covered, symbol_id, "book_cover"), start, end):
      unit_start = gap_end - gap_end % unit if gap_end % unit else gap_end - unit
      while unit_start + unit > gap_start:
        range_start, range_end = max(gap_start, unit_start), min(gap_end, unit_start + unit)
        self.status["fill"] = f"book {time.strftime('%Y-%m-%d %H:%M', time.gmtime(unit_start / 1000))} UTC"
        urls = (
          book.bybit_book_units(self.market, market_info["id"], unit_start)
          if exchange_id == "bybit"
          else [book.gate_book_units(self.market, market_info["id"], unit_start)]
        )
        replay = book.replay_bybit if exchange_id == "bybit" else book.replay_gate
        for url in urls:
          if url in self.missing and time.time() - self.missing[url] < RETRY_MISSING:
            continue
          if await self._book_file(
            url,
            lambda path, replayer=replay, range_start=range_start, range_end=range_end: self._write_columns(
              symbol_id, row, replayer(path, contract), range_start, range_end
            ),
          ):
            await asyncio.to_thread(self.w.db.add_cover, symbol_id, range_start, range_end, "archive", "book_cover")
            break
        unit_start -= unit

  async def _book_file(self, url: str, use) -> bool:
    tmp_dir = Path(tempfile.mkdtemp(dir=self.w.folder / "tmp"))
    try:
      if not await sources.download(self.w.http, url, tmp_dir / "f"):
        self.missing[url] = time.time()
        return False
      await asyncio.to_thread(use, tmp_dir / "f")
      return True
    finally:
      shutil.rmtree(tmp_dir, ignore_errors=True)

  def _write_columns(self, symbol_id: int, row: dict, frames, range_start: int, range_end: int) -> None:
    cols, imbalance = [], []
    for timestamp, bids, asks in frames:
      if not range_start <= timestamp < range_end:
        continue
      col = book.column(bids, asks, row["step"])
      if col:
        cols.append((timestamp, book.encode(*col)))
        imbalance.append((timestamp, *book.bands(bids, asks)))
      if len(cols) >= 2000:
        self.w.db.write_book(symbol_id, cols, imbalance, [])
        cols, imbalance = [], []
    self.w.db.write_book(symbol_id, cols, imbalance, [])

  def _write_bands(self, symbol_id: int, path: Path) -> None:
    rows = [(timestamp, None, band_values) for timestamp, band_values in book.read_binance_depth(path)]
    self.w.db.write_book(symbol_id, [], rows, [])

  def _write_range(self, symbol_id: int, row: dict, trades, range_start: int, range_end: int) -> None:
    # trades of [a, b) -> minutes, streamed (a month of a big coin doesn't fit in memory); files are in time order
    # except for small jitter, which a one-minute reorder window absorbs
    mins = Minutes(row["step"], row["big_usd"])
    heap: list[tuple[int, int, Trade]] = []  # (time, file order, trade): same-ms trades keep their file order
    newest = 0
    for seq, trade in enumerate(trades):
      if range_start <= trade[0] < range_end:
        heapq.heappush(heap, (trade[0], seq, trade))
        newest = max(newest, trade[0])
        if len(heap) >= 50_000:
          out = []
          while heap and heap[0][0] < newest - MINUTE:
            out.append(heapq.heappop(heap)[2])
          mins.add(out)
          if len(mins.done_bars) >= 1440:
            self.w.db.write(symbol_id, *mins.take())
    mins.add([entry[2] for entry in sorted(heap)])
    mins.close()
    self.w.db.write(symbol_id, *mins.take())
    if mins.dropped:
      log.info(f"{self.key}: {mins.dropped} trades more than a minute out of order, dropped")


class Worker:
  def __init__(self, folder: Path) -> None:
    self.folder = folder
    (folder / "tmp").mkdir(parents=True, exist_ok=True)
    for old in (folder / "tmp").iterdir():  # left by a killed worker
      shutil.rmtree(old, ignore_errors=True)
    self.db = OrderflowDb(folder / "orderflow.db")
    self.exchanges = Exchanges()
    self.pairs: dict[str, Pair] = {}
    self.fill_lock = asyncio.Lock()
    self.settings = dict(DEFAULTS)
    self.http = httpx.AsyncClient(timeout=httpx.Timeout(60, read=300), follow_redirects=True)
    self.started = time.time()

  async def run(self) -> None:
    tasks = [asyncio.create_task(self._status()), asyncio.create_task(self._prune())]
    try:
      while True:
        self.settings = DEFAULTS | read_json(self.folder / "settings.json", {})
        await self._sync(read_json(self.folder / "watch.json", {}).get("pairs", []))
        await asyncio.sleep(2)
    finally:
      for task in tasks:
        task.cancel()
      await asyncio.gather(*(pair.stop() for pair in self.pairs.values()), return_exceptions=True)
      await self.exchanges.close()
      await self.http.aclose()

  async def _sync(self, wanted: list[dict]) -> None:
    want = {}
    for spec in wanted[: self.settings["max_pairs"]]:
      want[key(spec["exchange"], spec["market"], spec["symbol"])] = spec
    for pair_key in [pair_key for pair_key in self.pairs if pair_key not in want]:
      await self.pairs.pop(pair_key).stop()
      log.info(f"stopped {pair_key}")
    for pair_key, spec in want.items():
      if pair_key not in self.pairs:
        pair = self.pairs[pair_key] = Pair(self, spec["exchange"], spec["market"], spec["symbol"])
        await pair.start()
        log.info(f"watching {pair_key}")

  async def _status(self) -> None:
    last_n: dict[str, int] = {}
    while True:
      pairs = []
      for pair_key, pair in self.pairs.items():
        rate = (pair.trades_n - last_n.get(pair_key, pair.trades_n)) / 5
        last_n[pair_key] = pair.trades_n
        pairs.append(pair.status | {"key": pair_key, "trades_s": round(rate, 1)})
      out = {"ts": time.time(), "started": self.started, "pairs": pairs, "settings": self.settings}
      tmp_path = self.folder / ".status.json.tmp"
      tmp_path.write_text(json.dumps(out))
      os.replace(tmp_path, self.folder / "status.json")
      await asyncio.sleep(5)

  async def _prune(self) -> None:
    while True:
      with contextlib.suppress(Exception):
        before = int((time.time() - self.settings["retention_days"] * 86400) * 1000)
        book_before = int((time.time() - self.settings["book_retention_days"] * 86400) * 1000)
        await asyncio.to_thread(self.db.prune, before, book_before)
      await asyncio.sleep(3600)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--data", required=True)
  args = parser.parse_args()
  logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
  worker = Worker(Path(args.data))

  async def run() -> None:
    task = asyncio.create_task(worker.run())
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
      loop.add_signal_handler(signum, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
      await task

  asyncio.run(run())


if __name__ == "__main__":
  main()
