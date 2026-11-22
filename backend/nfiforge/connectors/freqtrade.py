# one freqtrade bot: jwt login, scheduled rest polling, live message websocket

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx
import websockets

from nfiforge.config import BotConfig, PollIntervals
from nfiforge.connectors.market import CandleSource
from nfiforge.metrics import pct_change, resample_closes, rsi
from nfiforge.radar import COLUMNS as RADAR_COLUMNS
from nfiforge.radar import KEEP_S as RADAR_KEEP_S
from nfiforge.radar import Radar, tf_seconds
from nfiforge.store import Store

log = logging.getLogger(__name__)

# what we keep of /show_config (shown on Bot Health, used across pages)
CONFIG_KEYS = (
  "strategy",
  "strategy_version",
  "exchange",
  "trading_mode",
  "margin_mode",
  "dry_run",
  "stake_currency",
  "stake_amount",
  "available_capital",
  "max_open_trades",
  "timeframe",
  "state",
  "runmode",
  "bot_name",
  "position_adjustment_enable",
  "max_entry_position_adjustment",
  "stoploss",
  "stoploss_on_exchange",
  "use_custom_stoploss",
  "trailing_stop",
  "minimal_roi",
  "force_entry_enable",
  "short_allowed",
  "order_types",
  "unfilledtimeout",
  "demo_trading",
)


def config_view(config: dict[str, Any]) -> dict[str, Any]:
  return {key: config.get(key) for key in CONFIG_KEYS}


REMOVED = re.compile(r"Removed (\S+) from whitelist, because (.*)")
SECRET = re.compile(r"((?:token|access_token|refresh_token|password|secret|key)=)[^&\s\"']+", re.I)

API = "/api/v1"
WS_EVENTS = [
  "status",
  "warning",
  "exception",
  "startup",
  "entry",
  "entry_fill",
  "entry_cancel",
  "exit",
  "exit_fill",
  "exit_cancel",
  "protection_trigger",
  "protection_trigger_global",
  "liquidation_warning",
  "strategy_msg",
  "whitelist",
  "new_candle",
]


class AuthError(Exception):
  pass


# =============================================================================
# REST CLIENT
# =============================================================================
class FreqtradeClient:
  # logs in once, refreshes the access token, logs in again on 401

  def __init__(self, bot: BotConfig, timeout: float = 10) -> None:
    self.bot = bot
    self._http = httpx.AsyncClient(base_url=bot.url + API, timeout=timeout)
    self.access_token: str | None = None
    self._refresh_token: str | None = None
    self.last_latency_ms: float | None = None

  async def close(self) -> None:
    await self._http.aclose()

  async def login(self) -> None:
    response = await self._http.post("/token/login", auth=(self.bot.username, self.bot.password or ""))
    if response.status_code == 401:
      raise AuthError(f"{self.bot.name}: freqtrade rejected username/password (401)")
    response.raise_for_status()
    body = response.json()
    self.access_token, self._refresh_token = body["access_token"], body["refresh_token"]

  async def _refresh(self) -> bool:
    if not self._refresh_token:
      return False
    response = await self._http.post("/token/refresh", headers={"Authorization": f"Bearer {self._refresh_token}"})
    if response.status_code != 200:
      return False
    self.access_token = response.json()["access_token"]
    return True

  async def request(self, method: str, path: str, **kwargs: Any) -> Any:
    if not self.access_token:
      await self.login()
    for attempt in range(2):
      started = time.perf_counter()
      try:
        response = await self._http.request(
          method, path, headers={"Authorization": f"Bearer {self.access_token}"}, **kwargs
        )
      except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError):
        # freqtrade drops idle keep-alive connections after ~5 s, same as our poll interval: retry once on a fresh one
        if attempt:
          raise
        continue
      self.last_latency_ms = (time.perf_counter() - started) * 1000
      if response.status_code == 401 and attempt == 0:
        if not await self._refresh():
          await self.login()
        continue
      response.raise_for_status()
      return response.json()
    raise AuthError(f"{self.bot.name}: still unauthorised after re-login")

  async def get(self, path: str, **params: Any) -> Any:
    return await self.request("GET", path, params=params or None)

  async def post(self, path: str, payload: dict[str, Any]) -> Any:
    return await self.request("POST", path, json=payload)

  # trade actions: a fresh connection (no stale keep-alive), never resent after a network error since the bot may
  # have got it already; only a 401 (refused before anything ran) is sent again after logging back in
  async def act(self, method: str, path: str, payload: dict[str, Any] | list[Any] | None = None) -> Any:
    if not self.access_token:
      await self.login()
    async with httpx.AsyncClient(base_url=self.bot.url + API, timeout=self._http.timeout) as http:
      for attempt in range(2):
        response = await http.request(
          method, path, headers={"Authorization": f"Bearer {self.access_token}"}, json=payload
        )
        if response.status_code == 401 and attempt == 0:
          if not await self._refresh():
            await self.login()
          continue
        response.raise_for_status()
        return response.json()
    raise AuthError(f"{self.bot.name}: still unauthorised after re-login")


# =============================================================================
# BOT CONNECTOR
# =============================================================================
# freqtrade's database has no id of its own, so a new one is spotted from the trades: the remembered oldest closed
# trade (id, open ms) now has another open time, or trades below its id appeared (a new database counts from 1
# again), or every closed trade is gone. losing only the oldest trades (deleted on the bot) is not a new database
def fresh_db(signature: tuple[int, int] | None, closed: dict[int, int]) -> bool:
  if signature is None:
    return False
  if not closed:
    return True
  trade_id, open_ms = signature
  if trade_id in closed:
    return closed[trade_id] != open_ms
  return min(closed) < trade_id


class BotConnector:
  # live view of one bot, every change goes out through publish

  def __init__(
    self,
    bot: BotConfig,
    poll: PollIntervals,
    publish: Callable[[dict[str, Any]], None],
    store: Store | None = None,
    notify: Callable[[str, str, Any], None] | None = None,
    market: CandleSource | None = None,
  ) -> None:
    self.bot = bot
    self.market = market  # public exchange candles, for btc when the bot doesn't trade it
    self.notify = notify  # trade events worth keeping as notifications
    self.store = store
    self._last_process_ts: float | None = None
    self._last_ok = 0.0  # last time any request to the bot answered
    self._err_path: str | None = None  # poll endpoint behind the current error; its next success clears it
    self.poll = poll
    self.publish = publish
    self.client = FreqtradeClient(bot)
    self.state: dict[str, Any] = {
      "name": bot.name,
      "url": bot.url,
      "connected": False,
      "ws_connected": False,
      "error": None,
      "is_nfi": False,
      "config": None,
      "version": None,
      "status": [],
      "health": None,
      "balance": None,
      "profit": None,
      "whitelist": None,
      "locks": None,
      "blacklist": None,
      "custom_data": None,
      "trades": None,
      "loop_s": None,
      "pulse": None,
      "pair_prices": {},
      "latency_ms": None,
      "fresh_db": False,  # the bot looks like it started on a new database: Manage Bots offers a reset
      "updated": {},
    }
    self.events: deque[dict[str, Any]] = deque(maxlen=500)
    self.history: dict[int, dict[str, Any]] = {}  # every closed trade by id
    self._history_wake = asyncio.Event()  # set when an open trade disappears: read the closes now, not next minute
    # log lines kept since start (freqtrade itself keeps only its last 1000): [date, ts s, logger, level, message]
    self.logs_kept: deque[list] = deque(maxlen=20000)
    self.logs_debug: deque[list] = deque(maxlen=2000)
    self.wl_changes: deque[dict[str, Any]] = deque(maxlen=2000)  # pairs joining / leaving the whitelist
    self._logs_gap = 0.0  # when a poll last found lines missing (the bot logs faster than we read)
    self._tasks: list[asyncio.Task] = []
    self._stopping = False
    self.radar = Radar(store, bot.name) if bot.radar else None

  # ---------------------------------------------------------------------------
  # LIFECYCLE
  # ---------------------------------------------------------------------------
  async def start(self) -> None:
    self._tasks = [
      asyncio.create_task(self._bootstrap_then_poll(), name=f"{self.bot.name}-poll"),
      asyncio.create_task(self._ws_loop(), name=f"{self.bot.name}-ws"),
    ]

  async def stop(self) -> None:
    # every loop also checks _stopping: a cancel that lands inside an http timeout can get swallowed, so keep
    # cancelling until all are done instead of waiting forever on one
    self._stopping = True
    while pending := [task for task in self._tasks if not task.done()]:
      for task in pending:
        task.cancel()
      await asyncio.wait(pending, timeout=1)
    await self.client.close()

  # ---------------------------------------------------------------------------
  # STATE
  # ---------------------------------------------------------------------------
  def _set(self, key: str, value: Any) -> None:
    if key == "health" and value:
      process_ts = value.get("last_process_ts")
      if process_ts and self._last_process_ts and process_ts != self._last_process_ts:
        self.state["loop_s"] = process_ts - self._last_process_ts
      if process_ts:
        self._last_process_ts = process_ts
    old = self.state["status"]
    if (
      key == "status"
      and isinstance(value, list)
      and isinstance(old, list)
      and ({trade["trade_id"] for trade in old} - {trade["trade_id"] for trade in value})
    ):
      self._history_wake.set()
    if key == "whitelist" and value and self.state["whitelist"]:
      old, new = set(self.state["whitelist"].get("whitelist") or []), set(value.get("whitelist") or [])
      now = time.time()
      self.wl_changes.extend({"ts": now, "pair": pair, "change": "added"} for pair in sorted(new - old))
      self.wl_changes.extend({"ts": now, "pair": pair, "change": "removed"} for pair in sorted(old - new))
    self.state[key] = value
    self.state["updated"][key] = time.time()
    self.publish({"type": "state_diff", "bot": self.bot.name, "data": {key: value}})

  def _fail(self, error: str, path: str | None = None) -> None:
    # one failed request (a dropped connection, one endpoint erroring) isn't the bot down: disconnected only when
    # nothing has answered for 15 s
    self._err_path = path
    down = time.time() - self._last_ok > 15
    if self.state["error"] != error or (down and self.state["connected"]):
      self.state.update(connected=self.state["connected"] and not down, error=error)
      self.publish(
        {"type": "state_diff", "bot": self.bot.name, "data": {"connected": self.state["connected"], "error": error}}
      )
      log.warning("%s", error)

  # ---------------------------------------------------------------------------
  # REST
  # ---------------------------------------------------------------------------
  async def _bootstrap(self) -> None:
    config = await self.client.get("/show_config")
    version = await self.client.get("/version")
    strategy = config.get("strategy") or ""
    self._set("config", config_view(config))
    self._set("version", version.get("version"))
    self._set("is_nfi", "nostalgiaforinfinity" in strategy.lower())
    self._last_ok = time.time()
    self.state.update(connected=True, error=None)
    self.publish({"type": "state_diff", "bot": self.bot.name, "data": {"connected": True, "error": None}})

  # after a bot control action: show running / paused / stopped now, not at the next config poll
  async def refresh_config(self) -> None:
    self._set("config", config_view(await self.client.get("/show_config")))

  # after a lock / blacklist edit: show it now, not at the next poll
  async def refresh(self, key: str, path: str) -> None:
    self._set(key, await self.client.get(path))

  async def _bootstrap_then_poll(self) -> None:
    backoff = 2.0
    while not self._stopping:
      try:
        await self._bootstrap()
        break
      except AuthError as e:
        self._fail(str(e))
        await asyncio.sleep(60)
      except Exception as e:
        self._fail(f"{self.bot.name}: cannot reach {self.bot.url} ({type(e).__name__}: {e})")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
    jobs = [
      ("status", "/status", self.poll.status),
      ("health", "/health", self.poll.health),
      ("balance", "/balance", self.poll.balance),
      ("profit", "/profit", self.poll.profit),
      ("whitelist", "/whitelist", self.poll.whitelist),
      ("config", "/show_config", 60, config_view),  # state (running / stopped) and config can change
      ("locks", "/locks", 60),
      ("blacklist", "/blacklist", 300),
    ]
    if self.state["is_nfi"]:
      jobs.append(("custom_data", "/trades/open/custom-data", self.poll.custom_data))
    loops = [self._poll_loop(*j) for j in jobs]
    loops += [self._history_loop(), self._pulse_loop(), self._prices_loop(), self._logs_loop()]
    if self.store:
      loops.append(self._equity_loop())
    if self.radar:
      loops.append(self._radar_loop())
    tasks = [asyncio.create_task(job) for job in loops]
    self._tasks += tasks  # stop() cancels each one itself
    await asyncio.gather(*tasks)

  async def _poll_loop(self, key: str, path: str, every: float, shape: Callable[[Any], Any] | None = None) -> None:
    while not self._stopping:
      try:
        response = await self.client.get(path)
        self._set(key, shape(response) if shape else response)
        self._last_ok = time.time()
        self.state["latency_ms"] = self.client.last_latency_ms
        if not self.state["connected"] or (self.state["error"] and self._err_path == path):
          self._err_path = None
          self.state.update(connected=True, error=None)
          self.publish({"type": "state_diff", "bot": self.bot.name, "data": {"connected": True, "error": None}})
      except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:  # older freqtrade without this endpoint: stop asking
          log.info("%s: %s not available, skipping", self.bot.name, path)
          return
        self._fail(f"{self.bot.name}: {path} -> HTTP {e.response.status_code}", path)
      except Exception as e:
        self._fail(f"{self.bot.name}: {path} failed ({type(e).__name__}: {e})", path)
      await asyncio.sleep(every)

  # ---------------------------------------------------------------------------
  # TRADE HISTORY: a full read (paged by id) every 30 min, which also drops trades deleted on the bot; in between the
  # newest closes are merged every minute, or as soon as an open trade closes
  # ---------------------------------------------------------------------------
  async def _history_loop(self) -> None:
    synced = 0.0
    while not self._stopping:
      try:
        full = time.time() - synced > 1800
        await self.sync_history(full)
        if full:
          synced = time.time()
      except Exception as e:
        log.info("%s: trade history failed (%s)", self.bot.name, e)
      with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(self._history_wake.wait(), 60)
      self._history_wake.clear()

  async def sync_history(self, full: bool) -> None:
    if full:
      trades, offset = {}, 0
      while True:
        page = await self.client.get("/trades", limit=500, offset=offset, order_by_id="true")
        rows = page.get("trades") or []
        trades.update({trade["trade_id"]: trade for trade in rows})
        offset += len(rows)
        if len(rows) < 500:
          break
      self.history = trades
    else:
      page = await self.client.get("/trades", limit=50)
      self.history.update({trade["trade_id"]: trade for trade in page.get("trades") or []})
    # newest 200, and every close of the last 2 days so "today" is whole in any time zone
    by_close = sorted(self.history.values(), key=lambda trade: trade.get("close_timestamp") or 0, reverse=True)
    recent = (time.time() - 2 * 86400) * 1000
    latest = [trade for i, trade in enumerate(by_close) if i < 200 or (trade.get("close_timestamp") or 0) >= recent]
    self._set("trades", {"trades": latest, "total": len(self.history)})
    if full and self.store:
      await asyncio.to_thread(self._check_db)

  # after each full read: compare the oldest closed trade with the one remembered (see fresh_db)
  def _check_db(self) -> None:
    closed = {
      trade["trade_id"]: trade.get("open_timestamp") or 0 for trade in self.history.values() if not trade.get("is_open")
    }
    signature = self.store.db_sig(self.bot.name)
    fresh = fresh_db(signature, closed)
    if not fresh and closed:
      oldest = min(closed)
      if signature != (oldest, closed[oldest]):
        self.store.set_db_sig(self.bot.name, (oldest, closed[oldest]))
    if fresh != self.state["fresh_db"]:
      self._set("fresh_db", fresh)

  # the log lines, whitelist changes and events kept since nfiforge started (Manage Bots reset)
  def clear_logs(self) -> None:
    for kept in (self.logs_kept, self.logs_debug, self.wl_changes, self.events):
      kept.clear()

  # ---------------------------------------------------------------------------
  # DERIVED: EQUITY, BTC PULSE, OPEN TRADE PRICES
  # ---------------------------------------------------------------------------
  async def _equity_loop(self) -> None:
    # one snapshot a minute: wallet total + open p&l (freqtrade keeps no equity history)
    while not self._stopping:
      await asyncio.sleep(60)
      balance, status = self.state["balance"], self.state["status"]
      if balance and status is not None and self.store:
        open_pnl = sum(trade.get("profit_abs") or 0 for trade in status)
        await asyncio.to_thread(self.store.add_equity, self.bot.name, wallet_of(balance) or 0, open_pnl)

  async def _logs_loop(self) -> None:
    # read freqtrade's last-1000-lines buffer every few seconds and keep what's new
    last_ts, edge = 0.0, set()
    while not self._stopping:
      try:
        response = await self.client.get("/logs", limit=1000)
        rows = [
          [date, timestamp / 1000 if timestamp > 1e11 else timestamp, logger, level, SECRET.sub(r"\1•••", message)]
          for date, timestamp, logger, level, message in response.get("logs") or []
        ]
        if rows and last_ts and rows[0][1] > last_ts:
          self._logs_gap = time.time()  # the oldest line returned is newer than the last one we have
        new = [
          entry for entry in rows if entry[1] > last_ts or (entry[1] == last_ts and (entry[2], entry[4]) not in edge)
        ]
        for entry in new:
          (self.logs_debug if entry[3] == "DEBUG" else self.logs_kept).append(entry)
          if self.radar and entry[3] != "DEBUG":
            self.radar.log(entry)
        if rows:
          last_ts = rows[-1][1]
          edge = {(entry[2], entry[4]) for entry in rows if entry[1] == last_ts}
      except Exception as e:
        log.debug("%s: logs poll failed: %s", self.bot.name, e)
      await asyncio.sleep(3)

  async def _radar_loop(self) -> None:
    # after each new candle (+30 s for the bot to analyse it): the last 3 candles of every whitelisted pair. the first
    # sweep fills the gap since the last saved one, or as much of the 7 days as the bot still holds
    first = True
    while not self._stopping:
      whitelist = (self.state["whitelist"] or {}).get("whitelist") or []
      timeframe = self.timeframe()
      seconds = tf_seconds(timeframe)
      gap = time.time() - (self.radar.resume or 0)
      limit = int(min(gap, RADAR_KEEP_S) // seconds) + 3 if first else 3
      for pair in whitelist:
        if self._stopping:
          return
        try:
          body = {"pair": pair, "timeframe": timeframe, "limit": limit, "columns": RADAR_COLUMNS}
          self.radar.add(pair, await self.client.post("/pair_candles", body))
        except Exception as e:
          log.debug("%s: radar %s failed: %s", self.bot.name, pair, e)
      if whitelist:
        self.radar.prune(whitelist, time.time())
        first = False
      now = time.time()
      await asyncio.sleep(
        (now // seconds + 1) * seconds + 30 - now if whitelist else 3
      )  # whitelist not loaded yet: soon

  def log_flags(self) -> tuple[bool, bool]:
    # (debug lines seen in the last 10 min, lines missed in the last 5 min)
    now = time.time()
    return bool(self.logs_debug and now - self.logs_debug[-1][1] < 600), now - self._logs_gap < 300

  def pairs(self) -> dict[str, Any]:
    # the pairlist side: whitelist, blacklist, locks, whitelist changes, and why pairs were filtered out (from the
    # pairlist filters' log lines; only as complete as the log is)
    filtered: dict[str, dict[str, Any]] = {}
    for _, timestamp, logger, _, msg in self.logs_kept:
      match = REMOVED.match(msg)
      if match:
        filtered[match[1]] = {"pair": match[1], "ts": timestamp, "filter": logger.split(".")[-1], "reason": match[2]}
    changes = []
    for change in self.wl_changes:
      removal = filtered.get(change["pair"])
      near = removal and change["change"] == "removed" and abs(removal["ts"] - change["ts"]) < 900
      changes.append({**change, "reason": f"{removal['filter']}: {removal['reason']}" if near else None})
    blacklist = self.state["blacklist"] or {}
    return {
      "whitelist": (self.state["whitelist"] or {}).get("whitelist") or [],
      "method": blacklist.get("method") or [],
      "blacklist": blacklist.get("blacklist") or [],
      "blacklist_expanded": blacklist.get("blacklist_expanded") or [],
      "locks": (self.state["locks"] or {}).get("locks") or [],
      "changes": changes[::-1],
      "filtered": sorted(filtered.values(), key=lambda removal: -removal["ts"]),
    }

  def logs(self, limit: int, debug: bool) -> dict[str, Any]:
    rows = (
      list(self.logs_kept) if not debug else sorted([*self.logs_kept, *self.logs_debug], key=lambda entry: entry[1])
    )
    missing = self.log_flags()[1]
    return {
      "warning": "the bot logs faster than its api keeps lines (debug level, -v?): some lines are missed"
      if missing
      else None,
      "logs": rows[-limit:],
    }

  def timeframe(self) -> str:
    return (self.state["config"] or {}).get("timeframe") or "5m"

  async def frame(self, pair: str, limit: int, columns: list[str] | None = None) -> dict[str, Any]:
    # the bot's own analysed candles; post asks for only the needed columns (nfi frames have hundreds),
    # older freqtrade: plain get with everything
    timeframe = self.timeframe()
    response = None
    if columns is not None:
      try:
        response = await self.client.post(
          "/pair_candles", {"pair": pair, "timeframe": timeframe, "limit": limit, "columns": columns}
        )
      except httpx.HTTPStatusError as e:
        if e.response.status_code not in (404, 405, 422):
          raise
    if response is None:
      response = await self.client.get("/pair_candles", pair=pair, timeframe=timeframe, limit=limit)
    return {"timeframe": timeframe, "columns": response.get("columns") or [], "data": response.get("data") or []}

  async def _candles(self, pair: str, limit: int, columns: list[str]) -> list[list[Any]]:
    frame = await self.frame(pair, limit, columns)
    cols = frame["columns"]
    indexes = [cols.index(column) for column in columns if column in cols]
    return [[row[i] for i in indexes] for row in frame["data"]]

  def _btc_pair(self) -> str | None:
    whitelist = (self.state["whitelist"] or {}).get("whitelist") or []
    stake = (self.state["config"] or {}).get("stake_currency") or "USDT"
    for pair in (f"BTC/{stake}:{stake}", f"BTC/{stake}"):
      if pair in whitelist:
        return pair
    return next((pair for pair in whitelist if pair.startswith("BTC/")), None)

  async def _btc_rows(self) -> tuple[str, list[list[Any]]] | None:
    # the bot's own 5m candles when btc is in its whitelist, else the exchange's public ones
    pair = self._btc_pair()
    if pair:
      return pair, await self._candles(pair, 1000, ["__date_ts", "open", "high", "low", "close", "volume"])
    config = self.state["config"] or {}
    if not (self.market and config.get("exchange") and self.state["whitelist"] is not None):
      return None  # config or whitelist not loaded yet
    stake = config.get("stake_currency") or "USDT"
    futures = config.get("trading_mode") == "futures"
    pair = f"BTC/{stake}:{stake}" if futures else f"BTC/{stake}"
    result = await self.market.latest(config["exchange"], futures, pair, "5m", 1000)
    return pair, result["candles"]

  async def _pulse_loop(self) -> None:
    # btc 5m candles: last 24h, change 15m/1h/4h/1d, 4h rsi
    while not self._stopping:
      try:
        got = await self._btc_rows()
        if not got:  # config or whitelist not loaded yet: check again soon
          await asyncio.sleep(5)
          continue
        pair, rows = got
        rows = [row for row in rows if row[4] is not None]
        if rows:
          closes = [row[4] for row in rows]
          ts_close = [[row[0] / 1000, row[4]] for row in rows]
          self._set(
            "pulse",
            {
              "pair": pair,
              "candles": rows[-288:],
              "change": {
                label: pct_change(closes, bars) for label, bars in (("15m", 3), ("1h", 12), ("4h", 48), ("1d", 288))
              },
              "rsi_4h": rsi(resample_closes(ts_close, 4 * 3600)),
            },
          )
      except Exception as e:
        log.info("%s: btc pulse failed (%s)", self.bot.name, e)
      await asyncio.sleep(60)

  async def _prices_loop(self) -> None:
    # last 24h of closes for each open trade's pair, for the slot card charts
    while not self._stopping:
      if not self.state["updated"].get("status"):  # open trades not loaded yet
        await asyncio.sleep(3)
        continue
      pairs = sorted({trade["pair"] for trade in self.state["status"] or []})
      prices: dict[str, list[list[float]]] = {}
      for pair in pairs:
        try:
          prices[pair] = [
            [row[0] / 1000, row[1]]
            for row in await self._candles(pair, 288, ["__date_ts", "close"])
            if row[1] is not None
          ]
        except Exception as e:
          log.info("%s: prices for %s failed (%s)", self.bot.name, pair, e)
      self._set("pair_prices", prices)
      await asyncio.sleep(300 if pairs else 30)

  # ---------------------------------------------------------------------------
  # WEBSOCKET
  # ---------------------------------------------------------------------------
  def _ws_url(self) -> str:
    base = self.bot.url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return f"{base}{API}/message/ws?token={self.client.access_token}"

  async def _ws_loop(self) -> None:
    backoff = 2.0
    while not self._stopping:
      try:
        if not self.client.access_token:
          await self.client.login()
        async with websockets.connect(self._ws_url(), open_timeout=10, ping_interval=20) as websocket:
          await websocket.send(json.dumps({"type": "subscribe", "data": WS_EVENTS}))
          self.state["ws_connected"] = True
          self.publish({"type": "state_diff", "bot": self.bot.name, "data": {"ws_connected": True}})
          backoff = 2.0
          async for raw in websocket:
            self._on_ws_message(json.loads(raw))
      except asyncio.CancelledError:
        raise
      except Exception as e:
        if self.state["ws_connected"]:
          self.state["ws_connected"] = False
          self.publish({"type": "state_diff", "bot": self.bot.name, "data": {"ws_connected": False}})
        log.info("%s: websocket closed (%s), retry in %.0fs", self.bot.name, type(e).__name__, backoff)
        if isinstance(e, websockets.InvalidStatus):
          self.client.access_token = None  # token likely expired: re-login next round
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)

  def _on_ws_message(self, msg: dict[str, Any]) -> None:
    msg_type = msg.get("type")
    if msg_type not in WS_EVENTS:
      return
    # freqtrade sends most messages flat ({"type": "exit_fill", "pair": ...}); only a few wrap them in "data"
    data = msg["data"] if "data" in msg else {key: value for key, value in msg.items() if key != "type"}
    event = {"ts": time.time(), "type": msg_type, "data": data}
    self.events.append(event)
    self.publish({"type": "event", "bot": self.bot.name, "data": event})
    if self.notify:
      self.notify(self.bot.name, msg_type, data)
    if msg_type == "whitelist":
      self._set("whitelist", {"whitelist": msg.get("data")})


def wallet_of(balance: dict[str, Any]) -> float | None:
  # the stake coin's own wallet balance, without open p&l; freqtrade's "total" adds the positions' collateral, which
  # on live futures already holds their unrealised p&l, so wallet + open p&l from it counted the open loss twice
  stake = balance.get("stake")
  for currency in balance.get("currencies") or []:
    if currency.get("currency") == stake and not currency.get("is_position") and currency.get("balance") is not None:
      return float(currency["balance"])
  return balance.get("total")
