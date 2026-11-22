# where each exchange's trades come from. live: the exchange's public trade stream (ccxt pro, any exchange).
# history, best first: the exchange's own free archive files (daily or monthly), else its rest api paged through
# time, else only the most recent trades (history then starts when recording started)

from __future__ import annotations

import csv
import gzip
import io
import logging
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import ccxt.pro as ccxtpro
import httpx

from nfiforge.orderflow.aggregate import Trade

log = logging.getLogger(__name__)

DAY = 86_400_000
H8 = 8 * 3_600_000

# freqtrade exchange names that ccxt knows by another name
ALIASES = {"gateio": "gate", "huobi": "htx"}


def ccxt_id(exchange: str) -> str:
  return ALIASES.get(exchange, exchange)


def make_exchange(exchange: str, market: str) -> ccxtpro.Exchange:
  cls = getattr(ccxtpro, ccxt_id(exchange), None)
  if cls is None:
    raise ValueError(f"ccxt has no live data for {exchange}")
  return cls({"enableRateLimit": True, "options": {"defaultType": market}})


def to_trade(trade: dict, contract: float) -> Trade:
  # ccxt trade -> ours; side is the taker's side, amount is in contracts on contract markets
  return int(trade["timestamp"]), float(trade["price"]), float(trade["amount"]) * contract, trade["side"] == "buy"


# =============================================================================
# ARCHIVES: one unit = the files that cover [start, end) of one market
# =============================================================================
@dataclass
class Unit:
  start: int
  end: int
  urls: list[str]  # tried in order; the unit is there when the first one is (bitget: parts _001, _002, ...)
  parse: Callable[[Iterator[list[str]], float], Iterator[Trade]]
  parts: bool = False  # keep fetching numbered parts until one is missing


def _day(timestamp_ms: int) -> datetime:
  return datetime.fromtimestamp(timestamp_ms / 1000, UTC)


def _binance(rows: Iterator[list[str]], contract: float) -> Iterator[Trade]:
  # aggTrades: id, price, qty, first id, last id, time (ms; spot in us since 2025), buyer is maker[, best match]
  for fields in rows:
    if not fields or not fields[0][:1].isdigit():  # header (futures files have one)
      continue
    timestamp = int(fields[5])
    if timestamp > 10**14:
      timestamp //= 1000
    yield timestamp, float(fields[1]), float(fields[2]) * contract, fields[6][:1] in "fF"


def _bybit_swap(rows: Iterator[list[str]], contract: float) -> Iterator[Trade]:
  # timestamp (s), symbol, side, size, price, ...
  for fields in rows:
    if fields and fields[0][:1].isdigit():
      yield int(float(fields[0]) * 1000), float(fields[4]), float(fields[3]) * contract, fields[2] == "Buy"


def _bybit_spot(rows: Iterator[list[str]], contract: float) -> Iterator[Trade]:
  # id, timestamp (ms), price, volume, side
  for fields in rows:
    if fields and fields[0][:1].isdigit():
      yield int(fields[1]), float(fields[2]), float(fields[3]) * contract, fields[4] == "buy"


def _okx(rows: Iterator[list[str]], contract: float) -> Iterator[Trade]:
  # instrument_name, trade_id, side, price, size (contracts on swaps), created_time (ms)
  for fields in rows:
    if fields and fields[1][:1].isdigit():
      yield int(fields[5]), float(fields[3]), float(fields[4]) * contract, fields[2] == "buy"


def _gate_swap(rows: Iterator[list[str]], contract: float) -> Iterator[Trade]:
  # timestamp (s), id, price, size (contracts, negative = taker sold)
  for fields in rows:
    if fields and fields[0][:1].isdigit():
      size = float(fields[3])
      yield int(float(fields[0]) * 1000), float(fields[2]), abs(size) * contract, size > 0


def _gate_spot(rows: Iterator[list[str]], contract: float) -> Iterator[Trade]:
  # timestamp (s), id, price, amount, side (1 taker bought, 2 taker sold: checked by the tick rule, 76 % vs 24 %)
  for fields in rows:
    if fields and fields[0][:1].isdigit():
      yield int(float(fields[0]) * 1000), float(fields[2]), float(fields[3]) * contract, fields[4] == "1"


def _bitget(rows: Iterator[list[str]], contract: float) -> Iterator[Trade]:
  # trade_id, timestamp (ms), price, side, volume (quote), size (base)
  for fields in rows:
    if fields and fields[0][:1].isdigit():
      yield int(fields[1]), float(fields[2]), float(fields[5]) * contract, fields[3] == "buy"


def archive_units(exchange: str, market: str, mid: str, start: int, end: int) -> list[Unit]:
  # the archive units overlapping [start, end), newest first; [] when the exchange publishes no archive
  exchange_id, swap = ccxt_id(exchange), market == "swap"
  units: list[Unit] = []
  if exchange_id == "gate":
    month = _day(start).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while month.timestamp() * 1000 < end:
      next_month = (month + timedelta(days=32)).replace(day=1)
      kind = "futures_usdt/trades" if swap else "spot/deals"
      url = f"https://download.gatedata.org/{kind}/{month:%Y%m}/{mid}-{month:%Y%m}.csv.gz"
      parse = _gate_swap if swap else _gate_spot
      units.append(Unit(int(month.timestamp() * 1000), int(next_month.timestamp() * 1000), [url], parse))
      month = next_month
    return units[::-1]
  day = start - start % DAY
  if exchange_id in ("okx", "bitget"):  # files are utc+8 days: file D covers D-8h .. D+16h
    day -= DAY
  while day < end:
    date = _day(day)
    if exchange_id == "binance":
      kind = "futures/um" if swap else "spot"
      url = f"https://data.binance.vision/data/{kind}/daily/aggTrades/{mid}/{mid}-aggTrades-{date:%Y-%m-%d}.zip"
      units.append(Unit(day, day + DAY, [url], _binance))
    elif exchange_id == "bybit":
      url = (
        f"https://public.bybit.com/trading/{mid}/{mid}{date:%Y-%m-%d}.csv.gz"
        if swap
        else f"https://public.bybit.com/spot/{mid}/{mid}_{date:%Y-%m-%d}.csv.gz"
      )
      units.append(Unit(day, day + DAY, [url], _bybit_swap if swap else _bybit_spot))
    elif exchange_id == "okx":
      url = f"https://static.okx.com/cdn/okex/traderecords/trades/daily/{date:%Y%m%d}/{mid}-trades-{date:%Y-%m-%d}.zip"
      units.append(Unit(day - H8, day + DAY - H8, [url], _okx))
    elif exchange_id == "bitget":
      base = f"https://img.bitgetimg.com/online/trades/{'UMCBL' if swap else 'SPBL'}/{mid}/{date:%Y%m%d}"
      units.append(
        Unit(day - H8, day + DAY - H8, [f"{base}_{part:03d}.zip" for part in range(1, 100)], _bitget, parts=True)
      )
    else:
      return []
    day += DAY
  return [unit for unit in units[::-1] if unit.end > start and unit.start < end]


def has_archive(exchange: str, market: str) -> bool:
  return ccxt_id(exchange) in ("binance", "bybit", "okx", "bitget", "gate")


async def download(client: httpx.AsyncClient, url: str, dest: Path) -> bool:
  # False when the file isn't there (not published, or not yet)
  async with client.stream("GET", url) as response:
    if response.status_code in (403, 404):
      return False
    response.raise_for_status()
    with open(dest, "wb") as f:
      async for chunk in response.aiter_bytes(1 << 20):
        f.write(chunk)
  return True


def read_rows(path: Path) -> Iterator[list[str]]:
  # csv rows of a downloaded .zip (every member) or .csv.gz
  if zipfile.is_zipfile(path):
    with zipfile.ZipFile(path) as archive:
      for name in archive.namelist():
        with archive.open(name) as f:
          yield from csv.reader(io.TextIOWrapper(f, encoding="utf-8", newline=""))
  else:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
      yield from csv.reader(f)


# =============================================================================
# REST: trades over a time range through the exchange's api
# =============================================================================
# forward: since= pages from the start. back: until= pages from the end (newest first).
# okx: its history endpoint, paged back by time. anything else: only the most recent trades
REST_MODE = {
  "binance": "forward",
  "kraken": "forward",
  "krakenfutures": "forward",
  "bitget": "back",
  "bitvavo": "back",
  "gate": "back",
  "okx": "okx",
}


def rest_mode(exchange: str) -> str:
  return REST_MODE.get(ccxt_id(exchange), "recent")


async def rest_trades(
  exchange: ccxtpro.Exchange,
  symbol: str,
  start: int,
  end: int,
  contract: float,
  progress: Callable[[int], None] | None = None,
) -> tuple[int, int, list[Trade]]:
  # (lo, hi, trades): [lo, hi) is complete. less than [start, end) when the api can't reach that far back (binance
  # futures: 2 days, gate spot: 30 days, most others: only the latest trades). network errors are raised
  mode = rest_mode(exchange.id)
  seen: set = set()
  out: list[Trade] = []

  def keep(batch: list[dict]) -> None:
    for trade in batch:
      trade_key = trade.get("id") or (trade["timestamp"], trade["price"], trade["amount"], trade["side"])
      if trade_key not in seen and start <= trade["timestamp"] < end:
        seen.add(trade_key)
        out.append(to_trade(trade, contract))

  def between(from_ms: int, to_ms: int) -> tuple[int, int, list[Trade]]:
    if from_ms >= to_ms:
      return end, end, []
    return from_ms, to_ms, sorted((trade for trade in out if from_ms <= trade[0] < to_ms), key=lambda row: row[0])

  if mode == "forward":
    cursor = start
    try:
      while cursor < end:
        batch = await exchange.fetch_trades(symbol, since=cursor, limit=1000)
        keep(batch)
        newest = max((fetched["timestamp"] for fetched in batch), default=cursor)
        if newest <= cursor:
          if len(batch) < 1000:
            cursor = end  # caught up with the newest trade
            break
          newest = cursor + 1  # a full page inside one millisecond
        cursor = newest
        if progress:
          progress(cursor)
    except ccxtpro.ExchangeError as e:  # refused (too long ago): what came before it still counts
      log.info(f"{exchange.id} {symbol} rest stopped at {cursor}: {e}")
      return between(start, cursor) if cursor > start else (end, end, [])
    return between(start, end)

  if mode in ("back", "okx"):
    cursor, window = end, 3_600_000
    try:
      while cursor > start:
        window_start = max(start, cursor - window)
        if mode == "okx":
          params = {"method": "publicGetMarketHistoryTrades", "type": "2", "after": str(cursor)}
          batch = await exchange.fetch_trades(symbol, limit=100, params=params)
          full = len(batch) >= 100
        else:
          batch = await exchange.fetch_trades(symbol, since=window_start, limit=1000, params={"until": cursor})
          full = len(batch) >= 1000
        batch = [fetched for fetched in batch if fetched["timestamp"] < cursor]
        if mode == "okx" and not batch:
          break  # its history endpoint goes no further back
        if full and mode != "okx" and cursor - window_start > 2000:
          oldest, newest = (
            min(fetched["timestamp"] for fetched in batch),
            max(fetched["timestamp"] for fetched in batch),
          )
          if oldest - window_start <= cursor - newest:
            window = (
              cursor - window_start
            ) // 2  # the api gave the oldest trades of a busy window: ask for a shorter one
            continue
        keep(batch)
        if full or mode == "okx":
          # newest-first page: complete from its oldest trade. the next page overlaps it by a second (some apis take
          # whole seconds, gate); seen ids drop the repeats
          oldest = min(fetched["timestamp"] for fetched in batch)
          next_cursor = oldest + 1000 if oldest + 1000 < cursor else oldest + 1
          cursor = next_cursor if next_cursor < cursor else cursor - 1
        else:
          cursor = window_start
          window = min(window * 2, 6 * 3_600_000)
        if progress:
          progress(cursor)
    except ccxtpro.ExchangeError as e:
      log.info(f"{exchange.id} {symbol} rest stopped at {cursor}: {e}")
    return between(max(start, cursor), end)

  try:
    keep(await exchange.fetch_trades(symbol, limit=1000))
  except ccxtpro.ExchangeError as e:
    log.info(f"{exchange.id} {symbol} recent trades refused: {e}")
  if not out:
    return end, end, []
  # the latest trades are complete from the oldest one returned: whole minutes from the next minute on
  oldest = min(fetched[0] for fetched in out)
  return between(oldest - oldest % 60_000 + 60_000, end)


async def fetch_unit(client: httpx.AsyncClient, unit: Unit, tmp_dir: Path) -> list[Path] | None:
  # the unit's files on disk, or None when the archive hasn't got it
  files = []
  for i, url in enumerate(unit.urls):
    dest = tmp_dir / f"part{i}"
    if not await download(client, url, dest):
      break
    files.append(dest)
    if not unit.parts:
      break
  return files or None


def unit_trades(files: list[Path], unit: Unit, contract: float) -> Iterator[Trade]:
  for path in files:
    yield from unit.parse(read_rows(path), contract)


# every exchange nostalgiaforinfinity ships configs for
NAMES = {
  "binance": "Binance",
  "bybit": "Bybit",
  "okx": "OKX",
  "gate": "Gate",
  "bitget": "Bitget",
  "hyperliquid": "Hyperliquid",
  "kraken": "Kraken",
  "krakenfutures": "Kraken Futures",
  "kucoin": "KuCoin",
  "mexc": "MEXC",
  "htx": "HTX",
  "bitvavo": "Bitvavo",
  "bitmart": "Bitmart",
}


def sources_table() -> list[dict]:
  # what the page and docs show per exchange
  rows = []
  for exchange, name in NAMES.items():
    rows.append(
      {
        "exchange": exchange,
        "name": name,
        "live": hasattr(ccxtpro, exchange),
        "archive": has_archive(exchange, "swap"),
        "rest": rest_mode(exchange),
      }
    )
  return rows
