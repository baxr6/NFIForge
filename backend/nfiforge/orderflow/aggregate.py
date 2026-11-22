# trades -> one-minute footprint: per minute the candle, buy / sell volume and counts, the delta path inside the
# minute (lowest, highest, at the high, at the low) and per price row the same split. every longer timeframe is summed
# from these minutes, so nothing has to be fetched again for a new timeframe

from __future__ import annotations

import math
from collections.abc import Iterable

Trade = tuple[int, float, float, bool]  # time ms, price, base amount, taker bought

MINUTE = 60_000
NICE = (1, 2, 2.5, 5)


def pick_step(price: float, tick: float, target: float = 0.0002) -> float:
  # price row size: a nice multiple of the tick near 2 basis points of the price (a 1 h bar shows ~20-50 rows;
  # the chart merges rows for coarser views)
  want = max(price * target, tick)
  exponent = math.floor(math.log10(want / tick))
  for scale in (10**exponent, 10 ** (exponent + 1)):
    for nice in NICE:
      multiple = nice * scale
      if multiple >= want / tick and abs(multiple - round(multiple)) < 1e-9:
        return round(round(multiple) * tick, 12)
  return round(math.ceil(want / tick) * tick, 12)


def big_size(values: list[float], pct: float, fixed: float = 0.0) -> float | None:
  # a big trade's least value (USD): `fixed`, else the top `pct` % of these trade values, never under 1000;
  # None while there are too few trades to tell
  if fixed > 0:
    return fixed
  if len(values) <= 50:
    return None
  ordered = sorted(values)
  return max(1000.0, ordered[max(0, int(len(ordered) * (1 - pct / 100)) - 1)])


class Minutes:
  # feeds trades in time order; finished minutes come out of take(). the open minute stays until a later trade
  # (or close()) finishes it
  def __init__(self, step: float, big_usd: float) -> None:
    self.step, self.big_usd = step, big_usd
    self.cur: dict | None = None
    self.done_bars: list[tuple] = []
    self.done_levels: list[tuple] = []
    self.big: list[tuple] = []
    self.dropped = 0  # trades older than the open minute

  def add(self, trades: Iterable[Trade]) -> None:
    step, big_usd = self.step, self.big_usd
    minute = self.cur
    for timestamp, price, qty, buy in trades:
      minute_start = timestamp - timestamp % MINUTE
      if minute is None or minute_start != minute["t"]:
        if minute is not None:
          if minute_start < minute["t"]:  # out of order (a late live message): dropped, the minute is already closed
            self.dropped += 1
            continue
          self._finish(minute)
        minute = self.cur = {
          "t": minute_start,
          "o": price,
          "h": price,
          "l": price,
          "c": price,
          "vb": 0.0,
          "vs": 0.0,
          "nb": 0,
          "ns": 0,
          "d": 0.0,
          "dmin": 0.0,
          "dmax": 0.0,
          "dh": 0.0,
          "dl": 0.0,
          "qmax": 0.0,
          "lv": {},
          "big": [],
        }
      row_index = math.floor(price / step + 1e-9)  # row p = prices [p * step, (p + 1) * step)
      row = minute["lv"].get(row_index)
      if row is None:
        row = minute["lv"][row_index] = [0.0, 0.0, 0, 0]
      if buy:
        minute["vb"] += qty
        minute["nb"] += 1
        minute["d"] += qty
        row[0] += qty
        row[2] += 1
      else:
        minute["vs"] += qty
        minute["ns"] += 1
        minute["d"] -= qty
        row[1] += qty
        row[3] += 1
      delta = minute["d"]
      if delta < minute["dmin"]:
        minute["dmin"] = delta
      if delta > minute["dmax"]:
        minute["dmax"] = delta
      # delta at the moment the minute made its high / low (COT high / low)
      first = minute["nb"] + minute["ns"] == 1
      if price > minute["h"] or first:
        minute["h"] = price
        minute["dh"] = delta
      if price < minute["l"] or first:
        minute["l"] = price
        minute["dl"] = delta
      minute["c"] = price
      if qty > minute["qmax"]:
        minute["qmax"] = qty
      if qty * price >= big_usd:
        minute["big"].append((timestamp, price, qty, int(buy)))

  def _finish(self, minute: dict) -> None:
    self.done_bars.append(_bar(minute))
    self.done_levels.extend(_levels(minute))
    self.big.extend(minute["big"])

  def close(self) -> None:
    # the open minute counts as finished (end of an archive file / of a fetched range)
    if self.cur is not None:
      self._finish(self.cur)
      self.cur = None

  def take(self) -> tuple[list[tuple], list[tuple], list[tuple]]:
    out = self.done_bars, self.done_levels, self.big
    self.done_bars, self.done_levels, self.big = [], [], []
    return out

  def peek(self) -> tuple[list[tuple], list[tuple], list[tuple]]:
    # the open minute as rows, for the live chart (not finished: written again, whole, next time)
    minute = self.cur
    if minute is None:
      return [], [], []
    return [_bar(minute)], _levels(minute), list(minute["big"])


BAR = ("t", "o", "h", "l", "c", "vb", "vs", "nb", "ns", "dmin", "dmax", "dh", "dl", "qmax")


def _bar(minute: dict) -> tuple:
  return tuple(minute[key] for key in BAR)


def _levels(minute: dict) -> list[tuple]:
  return [(minute["t"], row_index, row[0], row[1], row[2], row[3]) for row_index, row in minute["lv"].items()]


def merge(bars: list[tuple], levels: list[tuple], tf_ms: int) -> list[dict]:
  # one-minute rows (time order) -> bars of tf_ms; the delta path is carried across the minutes inside a bar
  out: list[dict] = []
  by_t: dict[int, dict] = {}
  for (
    minute_start,
    open_price,
    high,
    low,
    close,
    buy_volume,
    sell_volume,
    buy_count,
    sell_count,
    delta_min,
    delta_max,
    delta_at_high,
    delta_at_low,
    max_qty,
  ) in bars:
    bar_start = minute_start - minute_start % tf_ms
    bar = by_t.get(bar_start)
    if bar is None:
      bar = by_t[bar_start] = {
        "t": bar_start,
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "vb": 0.0,
        "vs": 0.0,
        "nb": 0,
        "ns": 0,
        "dmin": 0.0,
        "dmax": 0.0,
        "dh": 0.0,
        "dl": 0.0,
        "qmax": 0.0,
        "first": minute_start,
        "levels": {},
      }
      out.append(bar)
    before = bar["vb"] - bar["vs"]  # running delta before this minute
    if high > bar["h"] or minute_start == bar["first"]:
      bar["h"], bar["dh"] = high, before + delta_at_high
    if low < bar["l"] or minute_start == bar["first"]:
      bar["l"], bar["dl"] = low, before + delta_at_low
    bar["dmin"] = min(bar["dmin"], before + delta_min)
    bar["dmax"] = max(bar["dmax"], before + delta_max)
    bar["c"] = close
    bar["vb"] += buy_volume
    bar["vs"] += sell_volume
    bar["nb"] += buy_count
    bar["ns"] += sell_count
    bar["qmax"] = max(bar["qmax"], max_qty)
  for minute_start, row_index, buy_volume, sell_volume, buy_count, sell_count in levels:
    bar = by_t.get(minute_start - minute_start % tf_ms)
    if bar is None:
      continue
    row = bar["levels"].get(row_index)
    if row is None:
      bar["levels"][row_index] = [buy_volume, sell_volume, buy_count, sell_count]
    else:
      row[0] += buy_volume
      row[1] += sell_volume
      row[2] += buy_count
      row[3] += sell_count
  for bar in out:
    del bar["first"]
  return out
