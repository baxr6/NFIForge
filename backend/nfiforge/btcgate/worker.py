# btcgate worker: a process of its own, started by the supervisor (python -m nfiforge.btcgate.worker --data DIR).
# runs the btcgate engine on binance futures: picks the coins like nexusforge's pairlist, keeps their candles like
# freqtrade does, and after every closed 5m candle calculates each coin's labels. writes status.json (health) and
# snapshot.json (each coin's latest labels, for the pages) next to the btcgate databases

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import signal
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd
from btcgate import __version__ as BTCGATE_VERSION
from btcgate.book import (
  btcgate_book_alert,
  btcgate_book_closes,
  btcgate_book_positions,
  btcgate_book_stats,
  btcgate_book_text,
)
from btcgate.buyback import BUYBACK_MIN_PCT, btcgate_buyback_load
from btcgate.db import btcgate_db
from btcgate.engine import BTCGateEngine
from btcgate.scanner import CHECK_NAMES, REVIEW_AT, btcgate_scan_new, btcgate_scan_text
from btcgate.settings import btcgate_settings

from nfiforge.btcgate.settings import OFF, SECRETS

log = logging.getLogger("nfiforge.btcgate")

TF_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
KEEP = BTCGateEngine.STARTUP + 100  # candles kept per coin and timeframe
EMPTY = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
# first start: the ledger on, nothing that needs other bots (the settings page comes later)
FIRST_SETTINGS = {"ledger": {"test_signals": True}, "probes": {"enabled": False}, "book": {"enabled": False}}
FIRST_SECRET = {"flow": {"coinalyze_api_key": ""}}  # direction label; paste the key, restart nfiforge
# coin list = nexusforge's pairlist on binance: top 200 by volume, then age / price / spread / range filters, top 150
CANDIDATES, COINS, MIN_DAYS, LOW_PRICE, MAX_SPREAD = 200, 150, 60, 0.003, 0.005
RANGE_DAYS, RANGE_MIN, RANGE_MAX = 3, 0.03, 0.95
BLACKLIST = [r"(USDC|FDUSD|TUSD|USDP|DAI|BUSD|USDE|USD1|BFUSD|XUSD|EUR)/.*", r"(BTCDOM|DEFI)/.*"]  # not coins
PICK_EVERY = 1800
SIGNALS_MAX = 1_000_000
# the alerts the signals tab scores, and the way each says price goes (0 = no side: contested)
EVENT_SIDE = {
  "forced_dump": 1,
  "forced_squeeze": -1,
  "dir_catchup": 1,
  "dir_catchup_base": 1,
  "warn_absorb": -1,
  "fp_contested": 0,
}
HORIZONS = {"1h": 12, "4h": 48, "24h": 288}  # in 5m candles
EVENT_DAYS = 7
SCAN_EVERY, RECOVERY_EVERY = 1800, 6 * 3600  # signals.jsonl starts over above this (nfiforge follows it from its end)


def write_json(path: Path, data: dict) -> None:
  # a temp name per thread: the candle threads report progress at the same time
  tmp_path = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
  tmp_path.write_text(json.dumps(data, default=str))
  os.replace(tmp_path, path)


class Weight:
  # binance allows 2,400 request weight a minute per ip, shared with the engine's own downloads: keep to 1,000
  def __init__(self, per_min: int = 1000):
    self.per_min, self.lock, self.used = per_min, threading.Lock(), []

  def take(self, weight: int) -> None:
    while True:
      with self.lock:
        now = time.monotonic()
        self.used = [(taken_at, spent) for taken_at, spent in self.used if now - taken_at < 60]
        if sum(spent for _, spent in self.used) + weight <= self.per_min:
          self.used.append((now, weight))
          return
      time.sleep(0.5)


def kline_weight(limit: int) -> int:
  return 1 if limit < 100 else 2 if limit < 500 else 5 if limit <= 1000 else 10


class Candles:
  # every coin's candles per timeframe, closed candles only and gaps filled the way freqtrade does; a copy on disk
  # so a restart only fetches what's new
  def __init__(self, exchange, weight: Weight, folder: Path):
    self.ex, self.weight, self.folder = exchange, weight, folder
    self.frames: dict[tuple[str, str], pd.DataFrame] = {}
    folder.mkdir(parents=True, exist_ok=True)

  def get(self, pair: str, timeframe: str) -> pd.DataFrame:
    return self.frames.get((pair, timeframe), EMPTY)

  def _file(self, pair: str, timeframe: str) -> Path:
    return self.folder / f"{re.sub(r'[^A-Za-z0-9]+', '_', pair)}-{timeframe}.pkl"

  def update(self, pair: str, timeframe: str, now_ms: int) -> None:
    step = TF_MS[timeframe]
    newest = now_ms // step * step - step  # open time of the newest closed candle
    df = self.frames.get((pair, timeframe))
    if df is None:
      path = self._file(pair, timeframe)
      df = pd.read_pickle(path) if path.exists() else EMPTY
    last = int(df["date"].iloc[-1].timestamp() * 1000) if len(df) else None
    if last is not None and last >= newest:
      self.frames[(pair, timeframe)] = df
      return
    if last is not None and newest - last < KEEP * step:
      since = last + step
    else:  # first load, or away so long the old candles are no use
      since, df = newest - (KEEP - 1) * step, EMPTY
    rows = []
    while since <= newest:
      limit = min(1000, (newest - since) // step + 1)
      self.weight.take(kline_weight(limit))
      batch = self.ex.fetch_ohlcv(pair, timeframe, since=since, limit=limit)
      rows += [candle for candle in batch if candle[0] <= newest]  # never the forming candle
      if len(batch) < limit:
        break
      since = batch[-1][0] + step
    if rows:
      new = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
      new["date"] = pd.to_datetime(new["date"], unit="ms", utc=True)
      new = new.astype({column: float for column in ("open", "high", "low", "close", "volume")})
      df = pd.concat([df, new]) if len(df) else new
      df = df.drop_duplicates("date", keep="last").sort_values("date")
      df = self._fill(df, timeframe).tail(KEEP).reset_index(drop=True)
    self.frames[(pair, timeframe)] = df

  @staticmethod
  def _fill(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    # a missing candle = previous close, no volume (freqtrade's ohlcv_fill_up_missing_data)
    full = pd.date_range(df["date"].iloc[0], df["date"].iloc[-1], freq=pd.Timedelta(milliseconds=TF_MS[timeframe]))
    if len(full) == len(df):
      return df
    df = df.set_index("date").reindex(full)
    df["close"] = df["close"].ffill()
    for col in ("open", "high", "low"):
      df[col] = df[col].fillna(df["close"])
    df["volume"] = df["volume"].fillna(0.0)
    return df.rename_axis("date").reset_index()

  def drop(self, keep: set[str]) -> None:
    for key in [frame_key for frame_key in self.frames if frame_key[0] not in keep]:
      del self.frames[key]

  def save(self) -> None:
    for (pair, timeframe), df in list(self.frames.items()):
      if len(df):
        tmp_path = self._file(pair, timeframe).with_suffix(".tmp")
        df.to_pickle(tmp_path)
        os.replace(tmp_path, self._file(pair, timeframe))


def binance_perps(exchange, weight: Weight) -> dict:
  weight.take(1)
  markets = exchange.load_markets(reload=True)
  return {
    symbol: market
    for symbol, market in markets.items()
    if market.get("swap")
    and market.get("linear")
    and market.get("settle") == "USDT"
    and market.get("active")
    and market["info"].get("contractType") == "PERPETUAL"
    and not any(re.fullmatch(pattern, symbol) for pattern in BLACKLIST)
  }


def pick_coins(exchange, weight: Weight, perps: dict) -> list[str]:
  weight.take(40)
  tickers = exchange.fetch_tickers()
  weight.take(5)
  books = exchange.fetch_bids_asks()
  ranked = sorted(
    (symbol for symbol in perps if tickers.get(symbol, {}).get("quoteVolume")),
    key=lambda symbol: -tickers[symbol]["quoteVolume"],
  )
  now = time.time() * 1000
  kept = []
  for symbol in ranked[:CANDIDATES]:
    market, last, book = perps[symbol], tickers[symbol].get("last"), books.get(symbol, {})
    listed = int(market["info"].get("onboardDate") or 0)
    tick = (market.get("precision") or {}).get("price")
    bid, ask = book.get("bid"), book.get("ask")
    if not listed or now - listed < MIN_DAYS * 86_400_000:
      continue
    if not last or not tick or tick / last > LOW_PRICE:
      continue
    if not bid or not ask or 1 - bid / ask > MAX_SPREAD:
      continue
    kept.append(symbol)

  def steady(symbol: str) -> bool:  # range over the last closed days, like RangeStabilityFilter
    weight.take(1)
    days = exchange.fetch_ohlcv(symbol, "1d", limit=RANGE_DAYS + 1)[:-1]
    if len(days) < RANGE_DAYS:
      return False
    low, high = min(day[3] for day in days), max(day[2] for day in days)
    return low > 0 and RANGE_MIN <= (high - low) / low <= RANGE_MAX

  with ThreadPoolExecutor(8) as pool:
    ok = list(pool.map(steady, kept))
  return [symbol for symbol, good in zip(kept, ok, strict=True) if good][:COINS]


def bare(pair: str) -> str:
  # the coin without its 1000 multiplier, which exchanges put in front or behind (1000PEPE, SHIB1000)
  return re.sub(r"^1000+|1000+$", "", pair.split("/")[0].upper()) or pair.split("/")[0].upper()


def to_binance(pairs: list[str], perps: dict) -> tuple[list[str], list[str]]:
  # the bots' pairs (any exchange) as binance perpetuals, and the coins binance has none for
  have: dict[str, str] = {}
  for symbol in sorted(
    perps, key=lambda symbol: symbol.split("/")[0] != bare(symbol)
  ):  # a plain symbol beats a 1000 one
    have.setdefault(bare(symbol), symbol)
  found, missing = [], []
  for pair in pairs:
    hit = have.get(bare(pair))
    if hit:
      found.append(hit)
    else:
      missing.append(bare(pair))
  return list(dict.fromkeys(found)), sorted(set(missing))


class BinanceFeed:
  # what the engine asks its host for (BTCGateEngine's docstring); funding comes from btcgate's own binance store
  exchange, stake, name = "binance", "USDT", "NFIForge"

  def __init__(self, worker: Worker):
    self.w = worker
    self.data_dir = str(worker.folder)

  def whitelist(self) -> list[str]:
    return list(self.w.coins)

  def pairlist(self) -> list[str]:  # "your pairlist" for the scanner: the bots' whitelists (the coin list until known)
    return to_binance(self.w.bot_coins[1], self.w.perps)[0] or list(self.w.coins)

  def book_report(self) -> str:  # /book: the bots nfiforge is connected to
    books = self.w.last_books
    return "⚖️ BTCGate book\n\n" + (
      "\n\n".join(btcgate_book_text(name, stats) for name, stats in books.items()) or "no bots connected"
    )

  def config_pairs(self) -> list[str]:
    return []  # no fixed pairs, the list is picked by volume

  def blacklist(self) -> list[str]:  # the bots' blacklists (the scanner skips them, recovery reviews them) + not-coins
    return list(BLACKLIST) + self.w.bot_blacklist

  def timerange(self):
    return None

  def candles(self, pair: str, timeframe: str) -> pd.DataFrame:
    return self.w.candles.get(pair, timeframe)

  def funding_candles(self, pair: str) -> pd.DataFrame:
    return EMPTY

  def analyzed(self, pair: str) -> pd.DataFrame:
    return self.w.analyzed.get(pair, EMPTY)

  def ticker(self, pair: str) -> dict:
    if pair not in self.w.tickers:
      self.w.weight.take(1)
      self.w.tickers[pair] = self.w.ex.fetch_ticker(pair)
    return self.w.tickers[pair]

  def tickers(self) -> dict:
    return self.w.tickers

  def markets(self) -> dict:
    return self.w.ex.markets

  def fetch_ohlcv(self, pair: str, timeframe: str, limit: int) -> list:
    self.w.weight.take(kline_weight(limit))
    return self.w.ex.fetch_ohlcv(pair, timeframe, limit=limit)

  def own_trades(self) -> list:
    return []


def load_settings(folder: Path) -> dict:
  # btcgate.json = btcgate's settings; btcgate_secret.json (owner only) adds keys and tokens to the same sections,
  # e.g. {"flow": {"coinalyze_api_key": "..."}}
  path, secret = folder / "btcgate.json", folder / "btcgate_secret.json"
  if not path.exists():
    write_json(path, FIRST_SETTINGS)
  if not secret.exists():  # owner-only from the start, with the key to fill in
    with os.fdopen(os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
      json.dump(FIRST_SECRET, f, indent=2)
  settings = json.loads(path.read_text())
  for section, values in json.loads(secret.read_text()).items():
    if isinstance(values, dict):  # an empty value is a key not filled in yet
      settings[section] = {
        **settings.get(section, {}),
        **{key: value for key, value in values.items() if value not in ("", None)},
      }
  return settings | OFF  # book and probes can't run here yet, whatever the file says


def read_state(path: Path) -> dict:
  try:
    return json.loads(path.read_text())
  except (OSError, ValueError):
    return {}


def last_row(df: pd.DataFrame) -> dict:
  # the newest candle's btcgate columns, numbers only (NaN -> None)
  row = df.iloc[-1]
  out = {"date": str(row["date"]), "close": float(row["close"])}
  for col in df.columns:
    if col.startswith("btcgate_") and isinstance(row[col], (int, float, np.number)) and not isinstance(row[col], bool):
      out[col[8:]] = None if pd.isna(row[col]) else float(row[col])
  return out


def score_events(rows: list[tuple], candles, now: pd.Timestamp) -> dict:
  # each alert's price then (its candle's close) and the move 1 h / 4 h / 24 h later, from the worker's 5m candles;
  # "usual" = how often the same coins moved that way over any such stretch in the same days, the bar to beat
  events, moves = [], {}
  for date, pair, layer, z_score in rows:
    df, side = candles(pair, "5m"), EVENT_SIDE[layer]
    row = {"date": date, "pair": pair, "layer": layer, "z": z_score, "side": side, "price": None}
    i = int(df["date"].searchsorted(pd.Timestamp(date))) if len(df) else 0
    if len(df) and i < len(df) and df["date"].iloc[i] == pd.Timestamp(date):
      close = df["close"].to_numpy()
      row["price"] = float(close[i])
      for horizon, bars in HORIZONS.items():
        row[horizon] = float(close[i + bars] / close[i] - 1) if i + bars < len(close) else None
      if side and pair not in moves:
        recent = df[df["date"] >= now - pd.Timedelta(days=EVENT_DAYS)]["close"].to_numpy()
        moves[pair] = {
          horizon: recent[bars:] / recent[:-bars] - 1 for horizon, bars in HORIZONS.items() if len(recent) > bars
        }
    events.append(row)
  summary = {}
  for layer, side in EVENT_SIDE.items():
    mine = [e for e in events if e["layer"] == layer and e["price"] is not None]
    if not mine or not side:
      continue
    out = {"n": len(mine)}
    for horizon in HORIZONS:
      done = [e[horizon] for e in mine if e.get(horizon) is not None]
      pooled = [
        move[horizon]
        for move in (moves.get(held_pair) for held_pair in {e["pair"] for e in mine})
        if move and horizon in move
      ]
      base = np.concatenate(pooled) if pooled else np.array([])
      out[horizon] = {
        "scored": len(done),
        "right": float(np.mean([change * side > 0 for change in done])) if done else None,
        "avg": float(np.mean(done)) if done else None,
        "usual": float(np.mean(base * side > 0)) if len(base) else None,
      }
    summary[layer] = out
  return {"time": time.time(), "days": EVENT_DAYS, "events": events, "summary": summary}


class Worker:
  def __init__(self, folder: Path):
    self.folder = folder
    self.stop = threading.Event()
    self.ex = ccxt.binanceusdm({"enableRateLimit": False})
    self.weight = Weight()
    self.candles = Candles(self.ex, self.weight, folder / "candles")
    self.settings = load_settings(folder)
    self.push = set(self.settings.pop("push", []))  # nfiforge's own key: alert types sent as phone push
    self.book_alerts = self.settings.pop("book_alerts", {})  # nfiforge's own key: {max_swing_usd, min_bets, hours}
    self.book_px: dict = {}  # btcgate_book_closes' hourly cache
    self.book_alerted: dict[str, float] = {}
    # the worker runs the scanner (page, push, telegram); its engine never posts one by itself
    scan = dict(self.settings.get("scanner", {}))
    self.scan_on, self.recovery_hour = scan.get("enabled", True), scan.get("recovery_hour_utc", 22)
    self.settings["scanner"] = {**scan, "enabled": False}
    self.scan_busy, self.scan_t, self.rec_t = False, 0.0, 0.0
    # nfiforge's own key: "full" = nexusforge's pairlist, "bots" = the bots' coins (the ledger pauses: other universe)
    self.mode = "bots" if self.settings.pop("coins", "full") == "bots" else "full"
    if self.mode == "bots":
      self.settings.setdefault("ledger", {})["test_signals"] = False
    self.signals_lock = threading.Lock()
    effective, _ = btcgate_settings(self.settings)
    # the settings it runs with (btcgate's defaults filled in) for the settings page, without the keys
    shown = json.loads(json.dumps(effective))
    for section, name in SECRETS.values():
      shown[section][name] = None
    shown["scanner"]["enabled"] = self.scan_on
    write_json(folder / "effective.json", shown)
    # the engine reads binance candles from its own store; only the ledger and the base frame need these
    self.tfs = ["5m", "1h", "4h"] + ([] if effective["source"]["signals"] == "binance" else ["15m", "1d"])
    self.coins: list[str] = []
    self.perps: dict = {}
    self.picked: list[str] = []  # the volume list (full mode)
    self.bot_coins: tuple[float, list, list] = (0, [], [])  # bot_coins.json: mtime, whitelists, open trades
    self.books: dict[str, list] = {}  # bot_coins.json: each connected bot's open trades
    self.bot_blacklist: list[str] = []  # bot_coins.json: the bots' blacklists
    self.last_books: dict[str, dict] = {}
    self.tickers: dict = {}
    self.analyzed: dict[str, pd.DataFrame] = {}
    self.status = {"pid": os.getpid(), "btcgate": BTCGATE_VERSION, "started": time.time(), "phase": "starting"}
    # direction comes from coinalyze's flow data: without a key it never leaves warm-up
    has_key = effective["flow"]["coinalyze_api_key"] or os.environ.get("COINALYZE_API_KEY")
    self.status["no_flow_key"] = effective["flow"]["source"] == "coinalyze" and not has_key

  def hook_alerts(self) -> None:
    # every alert btcgate raises (forced moves, catch-up, lock) also goes to signals.jsonl for nfiforge: its
    # notifications and, for the types picked, phone push. same coin list and cooldown as telegram
    alerts, telegram = self.engine.alerts, self.engine.alerts.alert
    path, last = self.folder / "signals.jsonl", {}
    if path.exists() and path.stat().st_size > SIGNALS_MAX:
      path.write_text("")

    def alert(pair: str, signal: str, price: float | None = None, kind: str = "") -> bool:
      coin, now = pair.split("/")[0].upper(), time.time()
      if (not alerts.coins or coin in alerts.coins) and now - last.get((pair, signal), 0) >= alerts.cooldown:
        last[(pair, signal)] = now
        row = {"ts": now, "pair": pair, "signal": signal, "price": price, "kind": kind, "push": signal in self.push}
        with self.signals_lock, open(path, "a") as f:  # locks arrive from the announcements thread
          f.write(json.dumps(row) + "\n")
      return telegram(pair, signal, price, kind)

    alerts.alert = alert

  def set(self, **fields) -> None:
    self.status.update(fields, updated=time.time())
    write_json(self.folder / "status.json", self.status)

  def retry(self, what: str, job):
    wait = 10
    while not self.stop.is_set():
      try:
        return job()
      except Exception as e:  # noqa: BLE001
        log.warning(f"{what} failed ({e}), retry in {wait}s")
        self.set(error=f"{what}: {e}", error_at=time.time())
        self.stop.wait(wait)
        wait = min(wait * 2, 300)
    return None

  def choose(self) -> bool:
    # the coin list: full = the volume list, bots = the bots' whitelists + BTC; both always add the coins of open
    # trades, so a trade on a coin outside the list still gets labels. true when it changed
    path = self.folder / "bot_coins.json"
    mtime = path.stat().st_mtime if path.exists() else 0
    # both lists are replaced, never changed in place: held here (not their id(), which python reuses once freed)
    last = getattr(self, "_chosen", None)
    if last and last[0] == mtime and last[1] is self.picked and last[2] is self.perps:
      return False
    self._chosen = (mtime, self.picked, self.perps)
    if mtime != self.bot_coins[0]:
      try:
        data = json.loads(path.read_text())
        self.bot_coins = (mtime, list(data.get("whitelist", [])), list(data.get("open", [])))
        self.books = dict(data.get("books", {}))
        self.bot_blacklist = list(data.get("blacklist", []))
      except (OSError, ValueError):
        pass
    _, whitelist, open_ = self.bot_coins
    wanted = self.picked if self.mode == "full" else ["BTC/USDT:USDT", *whitelist]
    base, missing = to_binance(wanted, self.perps)
    extra, missing_open = to_binance(open_, self.perps)
    extra = [pair for pair in extra if pair not in base]
    coins = base + extra
    if self.mode == "full":  # the volume list is binance already; only open trades can lack a perpetual
      missing = []
    changed = coins != self.coins
    self.coins = coins
    self.set(
      coins=len(coins),
      mode=self.mode,
      extra=[pair.split("/")[0] for pair in extra],
      missing=sorted(set(missing) | set(missing_open)),
    )
    return changed

  def update_candles(self, coins: list[str], progress: bool = False) -> None:
    now, done = int(time.time() * 1000), [0]

    def one(pair: str) -> None:
      for timeframe in self.tfs:
        try:
          self.candles.update(pair, timeframe, now)
        except Exception as e:  # noqa: BLE001
          log.warning(f"candles {pair} {timeframe}: {e}")
      done[0] += 1
      if progress and done[0] % 10 == 0:
        self.set(phase=f"loading candles {done[0]}/{len(coins)}")

    with ThreadPoolExecutor(8) as pool:
      list(pool.map(one, coins))

  def analyse(self) -> None:
    started = time.time()
    self.update_candles(self.coins)
    try:
      self.weight.take(40)
      self.tickers = self.ex.fetch_tickers()
    except Exception as e:  # noqa: BLE001
      log.warning(f"tickers: {e}")
    coins = {}
    for pair in self.coins:
      frame = self.candles.get(pair, "5m")
      if frame.empty:
        continue
      try:
        out = self.engine.btcgate_indicators(frame.copy(), pair)
      except Exception as e:  # noqa: BLE001
        log.warning(f"btcgate {pair}: {e}")
        continue
      self.analyzed[pair] = out
      coins[pair] = last_row(out)
    for pair in [stale_pair for stale_pair in self.analyzed if stale_pair not in self.coins]:
      del self.analyzed[pair]
    # holder revenue (buybacks, staking payouts) as % of market cap a year, refreshed daily by the engine
    buyback = btcgate_buyback_load(self.engine.db) if self.engine.bg["scanner"]["buyback"] else None
    buyback = dict(zip(buyback["coin"], buyback["pct"], strict=True)) if buyback is not None else {}
    for pair, row in coins.items():
      pct = buyback.get(re.sub(r"^1000+", "", pair.split("/")[0].upper()))
      row["buyback_pct"] = pct if pct is not None and pct >= BUYBACK_MIN_PCT else None
    candle = max((coin["date"] for coin in coins.values()), default=None)
    snapshot = {
      "time": time.time(),
      "candle": candle,
      "coins": coins,
      "mode": self.mode,
      "missing": self.status.get("missing", []),
    }
    write_json(self.folder / "snapshot.json", snapshot)
    for what, job in (("scoring alerts", self.score), ("book", self.book)):
      try:
        job()
      except Exception as e:  # noqa: BLE001
        log.warning(f"{what}: {e}")
    self.set(phase="running", candle=candle, analysed=len(coins), analyse_s=round(time.time() - started, 1))
    log.info(f"{len(coins)} coins analysed in {time.time() - started:.0f}s")

  def book(self) -> None:
    # each bot's open trades as btcgate's book: how many independent bets, the likely 24 h swing. pairs as binance
    # symbols (the hourly closes are binance's); a coin binance doesn't list is shown as not measured
    books, now = {}, pd.Timestamp.now(tz="UTC")
    for name, trades in self.books.items():
      rows = []
      for trade in trades:
        hit, _ = to_binance([trade["pair"]], self.perps)
        rows.append({**trade, "pair": hit[0] if hit else trade["pair"]})
      positions = btcgate_book_positions(rows)
      stats = btcgate_book_stats(positions, btcgate_book_closes(BinanceFeed(self), list(positions.index), self.book_px))
      books[name] = stats
      self.book_alert(name, stats)
    self.last_books = books
    clean = json.loads(json.dumps(books, default=float).replace("NaN", "null"))
    write_json(self.folder / "book.json", {"time": time.time(), "books": clean})
    fin = lambda stats, key: stats[key] if np.isfinite(stats.get(key, np.nan)) else None  # noqa: E731
    rows = [
      (
        str(now.floor("h")),
        name,
        stats["n"],
        fin(stats, "eff"),
        fin(stats, "sd"),
        fin(stats, "naive_sd"),
        stats["gross"],
        stats["long"],
        stats["short"],
      )
      for name, stats in books.items()
    ]
    with btcgate_db(
      str(self.folder / "btcgate_monitor.sqlite")
    ) as connection:  # btcgate's own book table: a row per hour
      connection.execute(
        "create table if not exists book (at text, bot text, n int, eff real, sd real, naive_sd real,"
        " gross real, long real, short real, primary key (at, bot))"
      )
      connection.executemany("insert or replace into book values (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

  def book_alert(self, name: str, stats: dict) -> None:
    limits = self.book_alerts
    why = btcgate_book_alert(stats, limits.get("max_swing_usd", 0), limits.get("min_bets", 0))
    if not why or time.time() - self.book_alerted.get(name, 0) < limits.get("hours", 6) * 3600:
      return
    self.book_alerted[name] = time.time()
    row = {"ts": time.time(), "pair": name, "signal": "book", "price": None, "kind": why, "push": "book" in self.push}
    with self.signals_lock, open(self.folder / "signals.jsonl", "a") as f:
      f.write(json.dumps(row) + "\n")
    alerts = self.engine.alerts
    if alerts.on and "book" in alerts.signals:
      text = f"⚖️ BTCGate book — {name}: {why}\n\n" + btcgate_book_text(name, stats)
      threading.Thread(target=alerts._send, args=(text,), daemon=True).start()

  def scan_tick(self) -> None:
    # the coin scan every 30 min and the recovery list every 6 h for the page; a coin / label new in 24 h goes to
    # notifications (and push / telegram when picked); the recovery list to telegram once a day. in a thread: the
    # recovery list downloads candles
    now = time.time()
    state_file = self.folder / "scan_state.json"
    state = read_state(state_file)
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    rec_post = time.gmtime(now).tm_hour >= self.recovery_hour and state.get("rec_day") != today
    scan_due, rec_due = now - self.scan_t >= SCAN_EVERY, now - self.rec_t >= RECOVERY_EVERY or rec_post
    if not self.scan_on or self.scan_busy or not (scan_due or rec_due) or not self.tickers:
      return  # no tickers before the first pass: the scan would see an empty market
    self.scan_busy = True
    if scan_due:
      self.scan_t = now
    if rec_due:
      self.rec_t = now

    def run() -> None:
      try:
        if scan_due:
          self.scan(state)
        if rec_due:
          floor, rows = self.engine.btcgate_recovery_rows()
          shown = [row for row in rows if row["passed"] >= REVIEW_AT]
          out = {"time": time.time(), "floor": floor, "rows": shown, "check_names": CHECK_NAMES}
          write_json(self.folder / "recovery.json", out)
          if rec_post:
            state["rec_day"] = today
            if self.telegram("scanner") and shown:
              self.engine.alerts._send(self.engine.btcgate_recovery())
        write_json(state_file, state)
      except Exception as e:  # noqa: BLE001
        log.warning(f"scanner: {e}")
      finally:
        self.scan_busy = False

    threading.Thread(target=run, daemon=True).start()

  def scan(self, state: dict) -> None:
    rows, now = self.engine.btcgate_scan_rows(full=True)
    first = not state.get("primed")  # a first run takes what's flagged now as known: no burst of alerts
    seen = {tuple(key.split("|", 1)): pd.Timestamp(value) for key, value in state.get("seen", {}).items()}
    new = btcgate_scan_new({row["coin"]: row["labels"] for row in rows}, seen, now)
    seen.update({(coin, lab): now for coin, labs in new.items() for lab in labs})
    state["seen"] = {
      f"{coin}|{lab}": str(seen_at) for (coin, lab), seen_at in seen.items() if now - seen_at <= pd.Timedelta(days=2)
    }
    state["primed"] = True
    clean = json.loads(json.dumps(rows, default=float).replace("NaN", "null"))
    write_json(self.folder / "scan.json", {"time": time.time(), "rows": clean})
    if first or not new:
      return
    with self.signals_lock, open(self.folder / "signals.jsonl", "a") as f:
      for row in rows:
        if row["coin"] in new:
          f.write(
            json.dumps(
              {
                "ts": time.time(),
                "pair": row["pair"],
                "signal": "scanner",
                "price": None,
                "kind": ", ".join(new[row["coin"]]),
                "push": "scanner" in self.push,
              }
            )
            + "\n"
          )
    if self.telegram("scanner"):
      fresh = [{**row, "labels": new[row["coin"]]} for row in rows if row["coin"] in new]
      self.engine.alerts._send(btcgate_scan_text(fresh, now))

  def telegram(self, kind: str) -> bool:
    return self.engine.alerts.on and kind in self.engine.alerts.signals

  def score(self) -> None:
    db_path = self.folder / "btcgate_monitor.sqlite"
    if not db_path.exists():
      return
    now = pd.Timestamp.now(tz="UTC")
    since = str(now - pd.Timedelta(days=EVENT_DAYS))
    marks = ",".join("?" * len(EVENT_SIDE))
    sql = f"select date, pair, layer, z from fast_events where date >= ? and layer in ({marks}) order by date desc"
    with contextlib.closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)) as connection:
      try:
        rows = connection.execute(sql, (since, *EVENT_SIDE)).fetchall()
      except sqlite3.OperationalError:  # no table yet
        return
    write_json(self.folder / "events.json", score_events(rows, self.candles.get, now))

  def run(self) -> None:
    self.set(phase="loading markets")
    self.perps = self.retry("markets", lambda: binance_perps(self.ex, self.weight)) or {}
    if self.mode == "full":
      self.picked = self.retry("coin list", lambda: pick_coins(self.ex, self.weight, self.perps)) or []
    if self.stop.is_set():
      return
    self.choose()
    self.set(phase="starting btcgate")
    self.engine = BTCGateEngine(BinanceFeed(self), self.settings, live=True)
    self.engine.btcgate_start()
    self.hook_alerts()
    self.update_candles(self.coins, progress=True)
    self.candles.save()
    picked, saved, done = time.time(), time.time(), None
    while not self.stop.is_set():
      now = time.time()
      if now - picked >= PICK_EVERY:
        picked = now
        try:
          self.perps = binance_perps(self.ex, self.weight)
          if self.mode == "full":
            self.picked = pick_coins(self.ex, self.weight, self.perps)
        except Exception as e:  # noqa: BLE001
          log.warning(f"coin list refresh failed, keeping the last one: {e}")
      if self.choose():  # new volume list, bot whitelist or open trade
        self.candles.drop(set(self.coins))
      try:
        self.engine.btcgate_loop()
        self.scan_tick()
      except Exception as e:  # noqa: BLE001
        log.warning(f"btcgate loop: {e}")
      step = int(now // 300 * 300)  # close time of the newest 5m candle
      if step != done and now - step >= 3:
        done = step
        self.analyse()
      if now - saved >= 3600:
        saved = now
        self.candles.save()
      self.stop.wait(5)

  def shutdown(self) -> None:
    self.candles.save()
    self.set(phase="stopped")


def main() -> None:
  parser = argparse.ArgumentParser(description="NFIForge btcgate worker")
  parser.add_argument("--data", required=True, help="btcgate data folder")
  args = parser.parse_args()
  logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
  for noisy in ("ccxt", "urllib3", "websockets"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
  folder = Path(args.data)
  folder.mkdir(parents=True, exist_ok=True)
  worker = Worker(folder)
  signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
  signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
  log.info(f"btcgate worker {BTCGATE_VERSION} starting in {folder}")
  code = 0
  try:
    worker.run()
  except Exception:  # noqa: BLE001
    log.exception("btcgate worker crashed")
    code = 1
  finally:
    try:
      worker.shutdown()
    except Exception:  # noqa: BLE001
      log.exception("btcgate worker shutdown failed")
    log.info("btcgate worker stopped")
    logging.shutdown()
    os._exit(code)  # btcgate's telegram and liquidation threads don't hold the process open


if __name__ == "__main__":
  main()
