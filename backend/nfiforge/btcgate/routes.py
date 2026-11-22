# /api/btcgate/...: the worker's health, every coin's latest labels and the signal ledger, read-only for everyone
# signed in. reads the worker's files and database, never imports btcgate itself

from __future__ import annotations

import asyncio
import contextlib
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter

from nfiforge.btcgate import settings
from nfiforge.btcgate.supervisor import Supervisor, read_json

LEDGER = """
select tag, side, count(*) as signals, count(outcome) as scored,
  avg(ret) * 100 as avg_pct,
  avg(case when outcome is not null then outcome = 'tp' end) * 100 as target_pct,
  avg(case when outcome is not null then outcome = 'sl' end) * 100 as stop_pct,
  avg(case when outcome is not null then outcome = 'time' end) * 100 as time_pct,
  count(distinct case when outcome is not null then substr(date, 1, 10) end) as days,
  min(date) as first
from signals group by tag, side order by tag, side
"""
# single-candle signals worth a look (the vol / oi switch-ons are too many to list)
EVENTS = """
select date, pair, layer, z from fast_events
where date >= ? and layer in (
  'forced_dump', 'forced_squeeze', 'fp_contested', 'dir_catchup', 'dir_catchup_base', 'warn_absorb'
)
order by date desc limit 300
"""
# the signals tab's list: every ledger signal of the last 30 days, the random control too (the page hides it)
SIGNALS = """
select date, pair, tag, side, price, outcome, ret * 100 as ret_pct, mfe * 100 as mfe_pct, mae * 100 as mae_pct
from signals where date >= ? order by date desc limit 2000
"""


def ledger(db_path: Path) -> dict:
  if not db_path.exists():
    return {"tags": []}
  with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)) as connection:
    connection.row_factory = sqlite3.Row
    try:
      return {"tags": [dict(row) for row in connection.execute(LEDGER)]}
    except sqlite3.OperationalError:  # the worker hasn't made the table yet
      return {"tags": []}


def events(db_path: Path, hours: float) -> list[dict]:
  if not db_path.exists():
    return []
  since = str(datetime.now(UTC) - timedelta(hours=hours)).replace("T", " ")
  with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)) as connection:
    connection.row_factory = sqlite3.Row
    try:
      return [dict(row) for row in connection.execute(EVENTS, (since,))]
    except sqlite3.OperationalError:
      return []


def signals(folder: Path) -> dict:
  # alerts with their result (the worker's events.json), the ledger's signals, and the bots' coins for the filter
  db_path, out = folder / "btcgate_monitor.sqlite", {"ledger": []}
  out["alerts"] = read_json(folder / "events.json") or {"events": [], "summary": {}}
  bots = read_json(folder / "bot_coins.json") or {}
  out["bot_pairs"] = sorted({*bots.get("whitelist", []), *bots.get("open", [])})
  if db_path.exists():
    since = str(datetime.now(UTC) - timedelta(days=30)).replace("T", " ")
    with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)) as connection:
      connection.row_factory = sqlite3.Row
      with contextlib.suppress(sqlite3.OperationalError):
        out["ledger"] = [dict(row) for row in connection.execute(SIGNALS, (since,))]
  return out


BOOK_HISTORY = "select at, bot, n, eff, sd, naive_sd, gross from book where at >= ? order by at"


def book(folder: Path) -> dict:
  # each bot's book now (the worker's book.json) and its hourly rows of the last 30 days
  out = read_json(folder / "book.json") or {"books": {}}
  out["history"] = []
  db_path = folder / "btcgate_monitor.sqlite"
  if db_path.exists():
    since = str(datetime.now(UTC) - timedelta(days=30)).replace("T", " ")
    with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)) as connection:
      connection.row_factory = sqlite3.Row
      with contextlib.suppress(sqlite3.OperationalError):
        out["history"] = [dict(row) for row in connection.execute(BOOK_HISTORY, (since,))]
  return out


NEWS = "select src, id, t, title from announcements where t >= ? and title like ? order by t desc limit 200"


def news_url(source: str, news_id: str) -> str | None:
  if news_id.startswith("http"):
    return news_id
  if source.startswith("binance"):
    return f"https://www.binance.com/en/support/announcement/detail/{news_id}"
  if source == "bitget_delist":
    return f"https://www.bitget.com/support/articles/{news_id}"
  if source == "upbit":
    return f"https://upbit.com/service_center/notice?id={news_id}"
  return None


def coin(folder: Path, name: str) -> dict:
  # one coin for a notification's popup: the last scan's reasons and the exchange news naming it (90 days)
  name = name.upper()
  scan = read_json(folder / "scan.json") or {}
  out = {"coin": name, "scan": next((row for row in scan.get("rows", []) if row.get("coin") == name), None), "news": []}
  db_path = folder / "btcgate_monitor.sqlite"
  if db_path.exists():
    since = int((datetime.now(UTC) - timedelta(days=90)).timestamp() * 1000)
    word = re.compile(rf"(?<![A-Z0-9]){re.escape(name)}(?![A-Z0-9])")  # EPIC, not EPICS or REPIC
    with (
      contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)) as connection,
      contextlib.suppress(sqlite3.OperationalError),
    ):
      rows = connection.execute(NEWS, (since, f"%{name}%")).fetchall()
      out["news"] = [
        {"src": source, "ts": timestamp_ms / 1000, "title": title, "url": news_url(source, news_id)}
        for source, news_id, timestamp_ms, title in rows
        if word.search(title)
      ][:20]
  return out


def router(gate: Supervisor) -> APIRouter:
  api = APIRouter(prefix="/api/btcgate")

  @api.get("/status")
  async def status():
    return gate.status()

  @api.get("/snapshot")
  async def snapshot():
    return await asyncio.to_thread(read_json, gate.folder / "snapshot.json") or {"coins": {}}

  @api.get("/ledger")
  async def get_ledger():
    return await asyncio.to_thread(ledger, gate.folder / "btcgate_monitor.sqlite")

  @api.get("/events")
  async def get_events(hours: float = 24):
    return await asyncio.to_thread(events, gate.folder / "btcgate_monitor.sqlite", min(max(hours, 1), 168))

  @api.get("/signals")
  async def get_signals():
    return await asyncio.to_thread(signals, gate.folder)

  @api.get("/book")
  async def get_book():
    return await asyncio.to_thread(book, gate.folder)

  @api.get("/scanner")
  async def get_scanner():  # the worker's last coin scan and recovery list
    def read():
      return {
        "scan": read_json(gate.folder / "scan.json") or {"rows": []},
        "recovery": read_json(gate.folder / "recovery.json") or {"rows": []},
      }

    return await asyncio.to_thread(read)

  @api.get("/coin/{name}")
  async def get_coin(name: str):
    return await asyncio.to_thread(coin, gate.folder, name[:30])

  @api.get("/settings")
  async def get_settings():
    return await asyncio.to_thread(settings.view, gate.folder)

  # admins only (app middleware: every btcgate write); the worker restarts to pick it up (~15 s with the cache)
  @api.put("/settings")
  async def put_settings(change: settings.Change):
    await asyncio.to_thread(settings.save, gate.folder, change)
    await gate.restart()
    return await asyncio.to_thread(settings.view, gate.folder)

  return api
