# order book -> what the page shows of it: heatmap columns (resting size per price row, every 10 s), book imbalance
# (bid vs ask value within set distances of the mid), and large orders appearing / pulled / filled. the same
# functions read the live book and the exchanges' book archives

from __future__ import annotations

import gzip
import json
import math
import struct
import zipfile
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

COLUMN_MS = 10_000
LOG = 1000  # stored size code = log1p(size) * LOG
SPAN_ROWS = 250  # rows kept each side of the mid in a heatmap column
BANDS = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05)  # imbalance distances from the mid
# deepest book each exchange streams (ccxt default when missing); bigger asks are refused by some
LIMITS = {
  "bybit": {"swap": 1000, "spot": 200},
  "binance": 1000,
  "okx": 400,
  "kraken": 1000,
  "htx": 400,
  "gate": 100,
  "krakenfutures": 1000,
  "bitvavo": 1000,
}

Levels = list[tuple[float, float]]  # (price, base amount), best first


def book_limit(exchange: str, market: str) -> int | None:
  limit = LIMITS.get(exchange)
  return limit.get(market) if isinstance(limit, dict) else limit


def column(bids: Levels, asks: Levels, step: float) -> tuple[int, list[float], list[float]] | None:
  # resting size per price row (row = floor(price / step), as the footprint), SPAN_ROWS each side of the mid
  if not bids or not asks:
    return None
  mid_row = math.floor((bids[0][0] + asks[0][0]) / 2 / step)
  low_row, width = mid_row - SPAN_ROWS, 2 * SPAN_ROWS + 1
  bid_sizes, ask_sizes = [0.0] * width, [0.0] * width
  for side, out in ((bids, bid_sizes), (asks, ask_sizes)):
    for price, qty in side:
      i = math.floor(price / step + 1e-9) - low_row
      if 0 <= i < width:
        out[i] += qty
      elif (side is bids and i < 0) or (side is asks and i >= width):
        break  # sorted best first: the rest is further out
  return low_row, bid_sizes, ask_sizes


def encode(low_row: int, bid_sizes: list[float], ask_sizes: list[float]) -> bytes:
  # empty rows trimmed at both ends; sizes as log codes (0.1 % steps: plenty for a picture), zlib
  used = [i for i in range(len(bid_sizes)) if bid_sizes[i] or ask_sizes[i]]
  if not used:
    return struct.pack("<ii", low_row, 0)
  first, last = used[0], used[-1] + 1
  width = last - first
  codes = [min(65535, round(math.log1p(size) * LOG)) for size in (*bid_sizes[first:last], *ask_sizes[first:last])]
  return struct.pack("<ii", low_row + first, width) + zlib.compress(struct.pack(f"<{2 * width}H", *codes), 6)


def decode(blob: bytes) -> tuple[int, list[float], list[float]]:
  low_row, width = struct.unpack_from("<ii", blob)
  if not width:
    return low_row, [], []
  sizes = [math.expm1(code / LOG) for code in struct.unpack(f"<{2 * width}H", zlib.decompress(blob[8:]))]
  return low_row, sizes[:width], sizes[width:]


def bands(bids: Levels, asks: Levels) -> tuple[float, list[float | None]]:
  # (mid, [bid value, ask value] per band); None where the book shown doesn't reach that far on a side
  mid = (bids[0][0] + asks[0][0]) / 2
  out: list[float | None] = []
  for distance in BANDS:
    for side, sign in ((bids, -1), (asks, 1)):
      edge = mid * (1 + sign * distance)
      reach = side[-1][0]
      if (sign < 0 and reach > edge) or (sign > 0 and reach < edge):
        out.append(None)
        continue
      out.append(sum(price * qty for price, qty in side if (price >= edge if sign < 0 else price <= edge)))
  return mid, out


class Walls:
  # large resting orders, by exact price. one counts (appear) after resting HOLD_MS at `usd` or more (market makers'
  # flickering quotes don't); when a counted one shrinks below that, the part that went was filled if trades at that
  # price took at least half of it, else pulled
  HOLD_MS = 10_000

  def __init__(self, usd: float) -> None:
    self.usd = usd
    self.seen: dict[tuple[int, float], int] = {}  # (1 bid / 0 ask, price) -> first time at size
    self.live: dict[tuple[int, float], float] = {}  # counted walls -> amount

  def update(self, timestamp: int, bids: Levels, asks: Levels, traded: dict[float, float]) -> list[tuple]:
    current = {(1, price): qty for price, qty in bids} | {(0, price): qty for price, qty in asks}
    big = {key: qty for key, qty in current.items() if key[1] * qty >= self.usd}
    self.seen = {key: self.seen.get(key, timestamp) for key in big}
    events = []
    for key, qty in big.items():
      if key not in self.live and timestamp - self.seen[key] >= self.HOLD_MS:
        events.append((timestamp, key[1], qty, key[0], "appear"))
        self.live[key] = qty
      elif key in self.live:
        self.live[key] = qty
    for key in [key for key in self.live if key not in big]:
      gone = self.live.pop(key) - current.get(key, 0.0)
      if gone > 0:
        kind = "filled" if traded.get(key[1], 0.0) >= gone * 0.5 else "pulled"
        events.append((timestamp, key[1], gone, key[0], kind))
    return events


def wall_usd(bids: Levels, asks: Levels, big_usd: float) -> float:
  # a wall: in the top 1 % of level values near the mid, and at least 5 big trades' worth
  values = sorted(price * qty for price, qty in [*bids[:200], *asks[:200]])
  top = values[int(len(values) * 0.99)] if len(values) > 20 else 0.0
  return max(top, 5 * big_usd)


# =============================================================================
# ARCHIVES (heavy: off unless book_history_days > 0)
# =============================================================================
class Book:
  # a book rebuilt from snapshot + update messages
  def __init__(self) -> None:
    self.b: dict[float, float] = {}
    self.a: dict[float, float] = {}

  def levels(self, depth: int = 1000) -> tuple[Levels, Levels]:
    bids = sorted(self.b.items(), key=lambda level: -level[0])[:depth]
    asks = sorted(self.a.items())[:depth]
    return bids, asks


def bybit_book_units(market: str, mid: str, day_ms: int) -> list[str]:
  day = datetime.fromtimestamp(day_ms / 1000, UTC).strftime("%Y-%m-%d")
  kind = "linear" if market == "swap" else "spot"
  base = f"https://quote-saver.bycsi.com/orderbook/{kind}/{mid}/{day}_{mid}"
  return [f"{base}_ob200.data.zip", f"{base}_ob500.data.zip"]  # ob500 until mid 2025, ob200 since


def replay_bybit(path: Path, contract: float) -> Iterator[tuple[int, Levels, Levels]]:
  # every COLUMN_MS: (ms, bids, asks) of the book at that moment
  book, next_ms = Book(), None
  with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as f:
    for line in f:
      msg = json.loads(line)
      timestamp, data = msg["ts"], msg["data"]
      while next_ms is not None and timestamp >= next_ms and book.b and book.a:  # one column per step, quiet ones too
        frame = book.levels()
        while timestamp >= next_ms:
          yield (next_ms, *frame)
          next_ms += COLUMN_MS
      if msg["type"] == "snapshot":
        book.b, book.a = {}, {}
        if next_ms is None:
          next_ms = timestamp - timestamp % COLUMN_MS + COLUMN_MS
      for key, side in (("b", book.b), ("a", book.a)):
        for price, qty in data.get(key, ()):
          price, qty = float(price), float(qty) * contract
          if qty:
            side[price] = qty
          else:
            side.pop(price, None)


def gate_book_units(market: str, mid: str, hour_ms: int) -> str:
  hour = datetime.fromtimestamp(hour_ms / 1000, UTC)
  kind = "futures_usdt" if market == "swap" else "spot"
  return f"https://download.gatedata.org/{kind}/orderbooks/{hour:%Y%m}/{mid}-{hour:%Y%m%d%H}.csv.gz"


def replay_gate(path: Path, contract: float) -> Iterator[tuple[int, Levels, Levels]]:
  # timestamp (s), set (snapshot row) / make (added) / take (removed), price, amount (negative = ask side), ...
  # rows of one snapshot share a timestamp; a set row at a new timestamp starts a new snapshot
  book, next_ms, snapshot_ts = Book(), None, None
  with gzip.open(path, "rt") as f:
    for line in f:
      fields = line.split(",")
      if len(fields) < 4 or not fields[0][:1].isdigit():
        continue
      timestamp, action, price, qty = (
        int(float(fields[0]) * 1000),
        fields[1],
        float(fields[2]),
        float(fields[3]) * contract,
      )
      side, qty = (book.a if qty < 0 else book.b), abs(qty)
      if action == "set":
        if timestamp != snapshot_ts:
          book.b, book.a, snapshot_ts = {}, {}, timestamp
          side = book.a if float(fields[3]) < 0 else book.b
          if next_ms is None:
            next_ms = timestamp - timestamp % COLUMN_MS + COLUMN_MS
        side[price] = qty
        continue
      snapshot_ts = None
      while next_ms is not None and timestamp >= next_ms and book.b and book.a:  # one column per step, quiet ones too
        frame = book.levels()
        while timestamp >= next_ms:
          yield (next_ms, *frame)
          next_ms += COLUMN_MS
      have = side.get(price, 0.0) + (qty if action == "make" else -qty)
      if have > 1e-12:
        side[price] = have
      else:
        side.pop(price, None)


def binance_depth_url(mid: str, day_ms: int) -> str:
  day = datetime.fromtimestamp(day_ms / 1000, UTC).strftime("%Y-%m-%d")
  return f"https://data.binance.vision/data/futures/um/daily/bookDepth/{mid}/{mid}-bookDepth-{day}.zip"


def read_binance_depth(path: Path) -> Iterator[tuple[int, list[float | None]]]:
  # timestamp, percentage (+-0.2, 1..5), depth, notional every ~30 s -> (ms, band values like bands()): the bands
  # binance has (0.2, 1, 2, 5 %) filled, the others None
  rows: dict[int, dict[float, float]] = {}
  with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as f:
    for raw in f:
      fields = raw.decode().strip().split(",")
      if not fields[0][:1].isdigit():
        continue
      timestamp = int(datetime.strptime(fields[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp() * 1000)
      rows.setdefault(timestamp, {})[round(float(fields[1]), 2)] = float(fields[3])
  for timestamp in sorted(rows):
    pct = rows[timestamp]
    out: list[float | None] = []
    for distance in BANDS:
      pct_key = round(distance * 100, 2)
      out += [pct.get(-pct_key), pct.get(pct_key)]
    yield timestamp, out
