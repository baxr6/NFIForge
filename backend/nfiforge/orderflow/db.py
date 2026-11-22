# the order flow database (sqlite, wal): the worker writes one-minute footprint rows, the dashboard reads them.
# cover = which time ranges are complete, so history is never fetched twice and a gap shows as a gap

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from pathlib import Path

from nfiforge.orderflow import book
from nfiforge.orderflow.aggregate import merge

SCHEMA = """
create table if not exists symbols (
  id integer primary key, key text unique not null, exchange text not null, market text not null,
  symbol text not null, step real not null, big_usd real not null, created real not null
);
create table if not exists bars (
  sym integer not null, t integer not null, o real, h real, l real, c real, vb real, vs real, nb integer,
  ns integer, dmin real, dmax real, dh real, dl real, qmax real, primary key (sym, t)
) without rowid;
create table if not exists levels (
  sym integer not null, t integer not null, p integer not null, vb real, vs real, nb integer, ns integer,
  primary key (sym, t, p)
) without rowid;
create table if not exists big (sym integer not null, ts integer not null, price real, qty real, buy integer);
create index if not exists big_ts on big (sym, ts);
create table if not exists cover (sym integer not null, start integer not null, "end" integer not null, source text);
create index if not exists cover_sym on cover (sym, start);
create table if not exists book_cols (
  sym integer not null, ts integer not null, blob blob, primary key (sym, ts)
) without rowid;
create table if not exists book_imb (
  sym integer not null, ts integer not null, mid real, bands text, primary key (sym, ts)
) without rowid;
create table if not exists book_events (
  sym integer not null, ts integer not null, price real, qty real, side integer, kind text
);
create index if not exists book_events_ts on book_events (sym, ts);
create table if not exists book_cover (
  sym integer not null, start integer not null, "end" integer not null, source text
);
create table if not exists oi (
  sym integer not null, ts integer not null, base real, primary key (sym, ts)
) without rowid;
create table if not exists funding (
  sym integer not null, ts integer not null, rate real, primary key (sym, ts)
) without rowid;
create table if not exists liqs (sym integer not null, ts integer not null, price real, qty real, long integer);
create index if not exists liqs_ts on liqs (sym, ts);
"""
# tables whose (start, end) ranges say what is complete: trades, book
COVERS = ("cover", "book_cover")


def key(exchange: str, market: str, symbol: str) -> str:
  return f"{exchange}|{market}|{symbol}"


class OrderflowDb:
  def __init__(self, path: Path, readonly: bool = False) -> None:
    self.path, self.readonly = path, readonly
    if not readonly:
      path.parent.mkdir(parents=True, exist_ok=True)
      with contextlib.closing(self._connect()) as connection, connection:
        connection.execute("pragma journal_mode=wal")
        connection.executescript(SCHEMA)

  def _connect(self) -> sqlite3.Connection:
    if self.readonly:
      return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=10)
    return sqlite3.connect(self.path, timeout=30)

  # ---------------------------------------------------------------------------
  # worker side
  # ---------------------------------------------------------------------------
  def symbol(self, exchange: str, market: str, symbol: str) -> dict | None:
    if self.readonly and not self.path.exists():
      return None
    with contextlib.closing(self._connect()) as connection:
      connection.row_factory = sqlite3.Row
      try:
        row = connection.execute("select * from symbols where key = ?", (key(exchange, market, symbol),)).fetchone()
      except sqlite3.OperationalError:  # no tables yet
        return None
    return dict(row) if row else None

  def add_symbol(self, exchange: str, market: str, symbol: str, step: float, big_usd: float) -> dict:
    with contextlib.closing(self._connect()) as connection, connection:
      connection.execute(
        "insert or ignore into symbols (key, exchange, market, symbol, step, big_usd, created) values (?,?,?,?,?,?,?)",
        (key(exchange, market, symbol), exchange, market, symbol, step, big_usd, time.time()),
      )
    return self.symbol(exchange, market, symbol)

  def set_big(self, symbol_id: int, big_usd: float) -> None:
    with contextlib.closing(self._connect()) as connection, connection:
      connection.execute("update symbols set big_usd = ? where id = ?", (big_usd, symbol_id))

  def write(self, symbol_id: int, bars: list[tuple], levels: list[tuple], big: list[tuple]) -> None:
    # rows are written for a whole range at once (the live open minute, a filled day): the range's old rows go first
    if not bars:
      return
    first, last = min(bar[0] for bar in bars), max(bar[0] for bar in bars)
    with contextlib.closing(self._connect()) as connection, connection:
      connection.execute("delete from bars where sym = ? and t between ? and ?", (symbol_id, first, last))
      connection.execute("delete from levels where sym = ? and t between ? and ?", (symbol_id, first, last))
      connection.execute("delete from big where sym = ? and ts >= ? and ts < ?", (symbol_id, first, last + 60_000))
      connection.executemany(
        "insert or replace into bars values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [(symbol_id, *bar) for bar in bars]
      )
      connection.executemany(
        "insert or replace into levels values (?,?,?,?,?,?,?)", [(symbol_id, *level) for level in levels]
      )
      connection.executemany("insert into big values (?,?,?,?,?)", [(symbol_id, *trade) for trade in big])

  def add_cover(self, symbol_id: int, start: int, end: int, source: str, table: str = "cover") -> None:
    # merged with any range it touches; the source of the newest piece is kept
    if table not in COVERS:
      raise ValueError(f"unknown cover table {table}")
    with contextlib.closing(self._connect()) as connection, connection:
      rows = connection.execute(
        f'select rowid, start, "end" from {table} where sym = ? and start <= ? and "end" >= ?', (symbol_id, end, start)
      ).fetchall()
      for rowid, row_start, row_end in rows:
        start, end = min(start, row_start), max(end, row_end)
        connection.execute(f"delete from {table} where rowid = ?", (rowid,))
      connection.execute(f"insert into {table} values (?,?,?,?)", (symbol_id, start, end, source))

  def covered(self, symbol_id: int, table: str = "cover") -> list[tuple[int, int, str]]:
    if table not in COVERS:
      raise ValueError(f"unknown cover table {table}")
    if self.readonly and not self.path.exists():
      return []
    with contextlib.closing(self._connect()) as connection:
      try:
        return connection.execute(
          f'select start, "end", source from {table} where sym = ? order by start', (symbol_id,)
        ).fetchall()
      except sqlite3.OperationalError:
        return []

  def traded(self, symbol_id: int, since: int) -> list[list]:
    # [row, bought, sold] per price row since `since` (ms)
    with contextlib.closing(self._connect()) as connection:
      rows = connection.execute(
        "select p, sum(vb), sum(vs) from levels where sym = ? and t >= ? group by p order by p", (symbol_id, since)
      ).fetchall()
    return [list(row) for row in rows]

  def has_imb(self, symbol_id: int, start: int, end: int) -> bool:
    with contextlib.closing(self._connect()) as connection:
      return (
        connection.execute(
          "select 1 from book_imb where sym = ? and ts >= ? and ts < ? limit 1", (symbol_id, start, end)
        ).fetchone()
        is not None
      )

  def write_book(
    self, symbol_id: int, cols: list[tuple[int, bytes]], imbalance: list[tuple[int, float, list]], events: list[tuple]
  ):
    with contextlib.closing(self._connect()) as connection, connection:
      connection.executemany(
        "insert or replace into book_cols values (?,?,?)", [(symbol_id, timestamp, blob) for timestamp, blob in cols]
      )
      connection.executemany(
        "insert or replace into book_imb values (?,?,?,?)",
        [(symbol_id, timestamp, mid, json.dumps(values)) for timestamp, mid, values in imbalance],
      )
      connection.executemany("insert into book_events values (?,?,?,?,?,?)", [(symbol_id, *event) for event in events])

  def write_derivs(self, symbol_id: int, open_interest=(), funding=(), liqs=()) -> None:
    # open interest points (ms, base), settled funding (ms, rate), liquidations (ms, price, base, long)
    with contextlib.closing(self._connect()) as connection, connection:
      connection.executemany("insert or replace into oi values (?,?,?)", [(symbol_id, *row) for row in open_interest])
      connection.executemany("insert or replace into funding values (?,?,?)", [(symbol_id, *row) for row in funding])
      connection.executemany("insert into liqs values (?,?,?,?,?)", [(symbol_id, *row) for row in liqs])

  def last_ts(self, symbol_id: int, table: str) -> int | None:
    if table not in ("oi", "funding", "liqs"):
      raise ValueError(f"unknown table {table}")
    with contextlib.closing(self._connect()) as connection:
      return connection.execute(f"select max(ts) from {table} where sym = ?", (symbol_id,)).fetchone()[0]

  def prune(self, before_ms: int, book_before_ms: int | None = None) -> None:
    book_before_ms = before_ms if book_before_ms is None else book_before_ms
    with contextlib.closing(self._connect()) as connection, connection:
      for table, col, cut in (
        ("bars", "t", before_ms),
        ("levels", "t", before_ms),
        ("big", "ts", before_ms),
        ("book_cols", "ts", book_before_ms),
        ("book_imb", "ts", book_before_ms),
        ("book_events", "ts", book_before_ms),
        ("oi", "ts", before_ms),
        ("funding", "ts", before_ms),
        ("liqs", "ts", before_ms),
      ):
        connection.execute(f"delete from {table} where {col} < ?", (cut,))
      for table, cut in (("cover", before_ms), ("book_cover", book_before_ms)):
        connection.execute(f'delete from {table} where "end" <= ?', (cut,))
        connection.execute(f"update {table} set start = ? where start < ?", (cut, cut))

  # ---------------------------------------------------------------------------
  # dashboard side
  # ---------------------------------------------------------------------------
  def read(self, symbol_id: int, tf_ms: int, start: int, end: int, rows: int) -> dict:
    # bars of tf_ms over [start, end); price rows merged `rows` at a time (row index = minute row // rows)
    start -= start % tf_ms
    with contextlib.closing(self._connect()) as connection:
      bars = connection.execute(
        "select t, o, h, l, c, vb, vs, nb, ns, dmin, dmax, dh, dl, qmax from bars where sym = ? and t >= ? and t < ?"
        " order by t",
        (symbol_id, start, end),
      ).fetchall()
      levels = connection.execute(
        f"select t - t % {tf_ms} as bt, p / ? as rp, sum(vb), sum(vs), sum(nb), sum(ns) from levels"
        " where sym = ? and t >= ? and t < ? group by bt, rp",
        (rows, symbol_id, start, end),
      ).fetchall()
      big = connection.execute(
        "select ts, price, qty, buy from big where sym = ? and ts >= ? and ts < ? order by ts", (symbol_id, start, end)
      ).fetchall()
    out = merge(bars, [], tf_ms)
    by_t = {bar["t"]: bar for bar in out}
    for bar_start, row_index, buy_volume, sell_volume, buy_count, sell_count in levels:
      bar = by_t.get(bar_start)
      if bar is not None:
        bar["levels"][row_index] = [buy_volume, sell_volume, buy_count, sell_count]
    return {"bars": out, "big": big}

  def heat(self, symbol_id: int, tf_ms: int, start: int, end: int, per_bar: int, rows: int) -> dict:
    # the book over [start, end): per bar `per_bar` columns (time-averaged resting size per merged row), the
    # imbalance per bar (averaged) and the large-order events
    start -= start % tf_ms
    slot_ms = max(1, tf_ms // per_bar)
    with contextlib.closing(self._connect()) as connection:
      cols = connection.execute(
        "select ts, blob from book_cols where sym = ? and ts >= ? and ts < ? order by ts", (symbol_id, start, end)
      ).fetchall()
      imbalance = connection.execute(
        "select ts, bands from book_imb where sym = ? and ts >= ? and ts < ? order by ts", (symbol_id, start, end)
      ).fetchall()
      events = connection.execute(
        "select ts, price, qty, side, kind from book_events where sym = ? and ts >= ? and ts < ? order by ts",
        (symbol_id, start, end),
      ).fetchall()
    # columns: summed per (time slot, row), then divided by the samples in the slot
    slots: dict[int, tuple[dict[int, float], dict[int, float], list[int]]] = {}
    for timestamp, blob in cols:
      low_row, bid_sizes, ask_sizes = book.decode(blob)
      slot = timestamp - timestamp % slot_ms
      slot_bids, slot_asks, samples = slots.setdefault(slot, ({}, {}, [0]))
      samples[0] += 1
      for side, sizes in ((slot_bids, bid_sizes), (slot_asks, ask_sizes)):
        for i, size in enumerate(sizes):
          if size:
            row = (low_row + i) // rows
            side[row] = side.get(row, 0.0) + size
    out_cols = []
    for slot in sorted(slots):
      slot_bids, slot_asks, samples = slots[slot]
      used_rows = sorted(set(slot_bids) | set(slot_asks))
      if not used_rows:
        continue
      low_row = used_rows[0]
      width = used_rows[-1] - low_row + 1
      bid_avg, ask_avg = [0.0] * width, [0.0] * width
      for row, size in slot_bids.items():
        bid_avg[row - low_row] = round(size / samples[0], 6)
      for row, size in slot_asks.items():
        ask_avg[row - low_row] = round(size / samples[0], 6)
      out_cols.append({"t": slot, "span": slot_ms, "lo": low_row, "b": bid_avg, "a": ask_avg})
    bars: dict[int, list] = {}
    for timestamp, raw in imbalance:
      bars.setdefault(timestamp - timestamp % tf_ms, []).append(json.loads(raw))
    imb_out = []
    for bar_start in sorted(bars):
      rows_ = bars[bar_start]
      sizes = []
      for band in range(len(book.BANDS) * 2):
        got = [row[band] for row in rows_ if row[band] is not None]
        sizes.append(sum(got) / len(got) if got else None)
      imb_out.append({"t": bar_start, "v": sizes})
    return {"cols": out_cols, "imb": imb_out, "events": events, "bands": book.BANDS}

  def derivs(self, symbol_id: int, tf_ms: int, start: int, end: int) -> dict:
    # per bar of tf_ms over [start, end): the last open interest in it, liquidated longs / shorts (value); the settled
    # funding rates from the last one before start
    start -= start % tf_ms
    with contextlib.closing(self._connect()) as connection:
      open_interest = connection.execute(
        f"select ts - ts % {tf_ms} as bt, base from oi where sym = ? and ts >= ? and ts < ? order by ts",
        (symbol_id, start, end),
      ).fetchall()
      liq = connection.execute(
        f"select ts - ts % {tf_ms} as bt, sum(case when long then price * qty else 0 end),"
        " sum(case when long then 0 else price * qty end), count(*) from liqs"
        " where sym = ? and ts >= ? and ts < ? group by bt order by bt",
        (symbol_id, start, end),
      ).fetchall()
      before = connection.execute(
        "select ts, rate from funding where sym = ? and ts < ? order by ts desc limit 1", (symbol_id, start)
      ).fetchall()
      funding = connection.execute(
        "select ts, rate from funding where sym = ? and ts >= ? and ts < ? order by ts", (symbol_id, start, end)
      ).fetchall()
    last: dict[int, float] = {}
    for bar_start, base in open_interest:
      last[bar_start] = base  # rows in time order: the bar's last point wins
    return {
      "oi": sorted(last.items()),
      "liq": [list(row) for row in liq],
      "funding": [list(row) for row in before + funding],
    }
