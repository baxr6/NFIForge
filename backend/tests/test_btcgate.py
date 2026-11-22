import json
import sqlite3

import httpx
import pytest
from nfiforge.btcgate.routes import ledger
from test_phase0 import _cfg, _signin


async def test_off_means_absent(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  assert not config.btcgate.enabled
  app = create_app(config)
  local = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=local, base_url="http://t") as client:
    assert (await client.get("/api/health")).json()["btcgate"] is False
    await _signin(app, client, role="viewer")
    assert (await client.get("/api/btcgate/status")).status_code == 404
  assert not (tmp_path / "btcgate").exists()


async def test_on_routes_for_viewers(fake, tmp_path, monkeypatch):
  _, url, _ = fake
  from nfiforge.app import create_app
  from nfiforge.btcgate import supervisor

  started = []
  monkeypatch.setattr(supervisor.Supervisor, "_run", lambda self: started.append(1) or _noop())
  restarts = []

  async def restart(self):
    restarts.append(1)

  monkeypatch.setattr(supervisor.Supervisor, "restart", restart)
  config = _cfg(url)
  config.data_dir = str(tmp_path)
  config.btcgate.enabled = True
  app = create_app(config)
  local = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=local, base_url="http://t") as client:
    assert (await client.get("/api/health")).json()["btcgate"] is True
    assert (await client.get("/api/btcgate/status")).status_code == 401  # signed in only
    await _signin(app, client, role="viewer")
    status = (await client.get("/api/btcgate/status")).json()
    assert status["memory_mb"] == 4096 and status["worker"] is None
    assert (await client.get("/api/btcgate/snapshot")).json() == {"coins": {}}
    assert (await client.get("/api/btcgate/ledger")).json() == {"tags": []}
    assert (await client.get("/api/btcgate/signals")).json() == {
      "ledger": [],
      "alerts": {"events": [], "summary": {}},
      "bot_pairs": [],
    }
    assert (await client.get("/api/btcgate/events")).json() == []
    # settings: viewers read, only admins change
    view = (await client.get("/api/btcgate/settings")).json()
    assert view["keys"] == {"coinalyze_api_key": False, "telegram_token": False, "chat_id": False}
    body = {"switches": {"fast.oi": False}, "secrets": {"telegram_token": "123:abc"}}
    assert (await client.put("/api/btcgate/settings", json=body)).status_code == 403
    await _signin(app, client, role="admin")
    assert (await client.put("/api/btcgate/settings", json={"switches": {"book.enabled": True}})).status_code == 422
    assert (await client.put("/api/btcgate/settings", json={"secrets": {"chat_id": "a b"}})).status_code == 422
    alerts = {"enabled": True, "signals": ["lock", "nope"], "coins": []}
    assert (await client.put("/api/btcgate/settings", json={"alerts": alerts})).status_code == 422
    assert (await client.put("/api/btcgate/settings", json={"push": ["nope"]})).status_code == 422
    body["alerts"] = {"enabled": True, "signals": ["lock", "catchup"], "coins": ["btc", " eth "]}
    body["push"] = ["lock", "lock"]
    response = await client.put("/api/btcgate/settings", json=body)
    assert response.status_code == 200 and restarts == [1]
    view = response.json()
    assert view["keys"]["telegram_token"] and "123:abc" not in response.text  # keys never go back to a browser
    fast_oi = next(item for section in view["sections"] for item in section["items"] if item["key"] == "fast.oi")
    assert fast_oi["on"] is False and fast_oi["needs"] == ["fast.enabled"]
    assert view["alerts"]["signals"] == ["catchup", "lock"] and view["alerts"]["coins"] == ["BTC", "ETH"]
    assert view["push"] == ["lock"]
  folder = tmp_path / "btcgate"
  saved = json.loads((folder / "btcgate.json").read_text())
  assert saved["fast"] == {"oi": False} and saved["book"] == {"enabled": False}
  assert (folder / "btcgate_secret.json").stat().st_mode & 0o777 == 0o600


async def _noop():
  return None


def test_ledger_scores_by_tag_and_side(tmp_path):
  db_path = tmp_path / "btcgate_monitor.sqlite"
  connection = sqlite3.connect(db_path)
  connection.execute(
    "create table signals (date text, pair text, tag text, side int, price real, outcome text, ret real)"
  )
  rows = [
    ("2026-10-01 10:00:00+00:00", "A/USDT:USDT", "core64", 1, 1.0, "tp", 0.04),
    ("2026-10-01 11:00:00+00:00", "B/USDT:USDT", "core64", 1, 1.0, "sl", -0.02),
    ("2026-10-02 10:00:00+00:00", "A/USDT:USDT", "core64", 1, 1.0, None, None),
    ("2026-10-01 10:00:00+00:00", "C/USDT:USDT", "random", -1, 1.0, "time", 0.01),
    ("2026-10-01 10:00:00+00:00", "D/USDT:USDT", "random", 1, 1.0, "sl", -0.03),
  ]
  connection.executemany("insert into signals values (?,?,?,?,?,?,?)", rows)
  connection.commit()
  connection.close()
  out = ledger(db_path)
  tags = {(tag["tag"], tag["side"]): tag for tag in out["tags"]}
  core = tags[("core64", 1)]
  assert core["signals"] == 3 and core["scored"] == 2 and core["days"] == 1
  assert core["avg_pct"] == pytest.approx(1.0) and core["target_pct"] == 50 and core["stop_pct"] == 50
  assert tags[("random", -1)]["time_pct"] == 100 and tags[("random", 1)]["stop_pct"] == 100
  assert ledger(tmp_path / "missing.sqlite") == {"tags": []}


def test_candle_gaps_filled_like_freqtrade():
  pytest.importorskip("btcgate")  # pandas comes with it
  import pandas as pd
  from nfiforge.btcgate.worker import Candles

  df = pd.DataFrame({"date": pd.to_datetime([0, 300_000, 900_000], unit="ms", utc=True)})
  df["open"], df["high"], df["low"] = [1.0, 2, 4], [1.0, 3, 5], [1.0, 1, 3]
  df["close"], df["volume"] = [1.0, 2.5, 4.5], [10.0, 20, 30]
  out = Candles._fill(df, "5m")
  assert len(out) == 4
  gap = out.iloc[2]
  assert gap["close"] == gap["open"] == gap["high"] == gap["low"] == 2.5 and gap["volume"] == 0


def test_secret_settings_merge(tmp_path):
  pytest.importorskip("btcgate")
  from nfiforge.btcgate.settings import OFF
  from nfiforge.btcgate.worker import FIRST_SECRET, FIRST_SETTINGS, load_settings

  # first start writes the defaults and an owner-only secret file with the key empty (empty = ignored)
  assert load_settings(tmp_path) == FIRST_SETTINGS | {"flow": {}}
  secret = tmp_path / "btcgate_secret.json"
  assert secret.stat().st_mode & 0o777 == 0o600 and json.loads(secret.read_text()) == FIRST_SECRET
  (tmp_path / "btcgate.json").write_text(json.dumps({"flow": {"source": "coinalyze", "coinalyze_api_key": "old"}}))
  assert load_settings(tmp_path)["flow"]["coinalyze_api_key"] == "old"
  secret.write_text(json.dumps({"flow": {"coinalyze_api_key": "k"}}))
  assert load_settings(tmp_path) == {"flow": {"source": "coinalyze", "coinalyze_api_key": "k"}} | OFF


async def test_worker_alerts_reach_notes_and_push(tmp_path):
  import asyncio

  from nfiforge.alerts import Notifier
  from nfiforge.btcgate.settings import ALERT_TYPES
  from nfiforge.btcgate.supervisor import Supervisor
  from nfiforge.settings import AlertSettings
  from nfiforge.store import Store

  published, pushed = [], []
  notifier = Notifier(Store(str(tmp_path)), AlertSettings, published.append, pushed.append)
  wording = {entry: (label, message) for entry, label, message in ALERT_TYPES}
  path = tmp_path / "signals.jsonl"
  path.write_text(json.dumps({"pair": "OLD/USDT:USDT", "signal": "lock", "push": True}) + "\n")  # before start: skipped
  gate = Supervisor(tmp_path, 4096, lambda row: notifier.btcgate_signal(row, *wording[row["signal"]]))
  task = asyncio.create_task(gate._follow(every=0.05))
  await asyncio.sleep(0.1)
  rows = [
    {"pair": "ABC/USDT:USDT", "signal": "lock", "kind": "delist", "price": None, "push": True},
    {"pair": "XYZ/USDT:USDT", "signal": "catchup", "kind": "", "price": 1.5, "push": False},
  ]
  with open(path, "a") as f:
    f.write(
      "".join(json.dumps(signal_row) + "\n" for signal_row in rows) + '{"pair": "half'
    )  # a line still being written waits
  await asyncio.sleep(0.2)
  task.cancel()
  notes = [sent["data"] for sent in published]
  assert [entry["title"] for entry in notes] == ["Lock: ABC", "Catch-up: XYZ"]
  assert notes[0]["kind"] == "signal" and notes[0]["bot"] == "BTCGate" and "(delist)" in notes[0]["detail"]
  assert "at 1.5" in notes[1]["detail"]
  assert [sent["title"] for sent in pushed] == ["Lock: ABC"]  # only the types picked for push


def test_worker_hook_writes_signals(tmp_path):
  pytest.importorskip("btcgate")
  from types import SimpleNamespace

  from nfiforge.btcgate.worker import Worker

  (tmp_path / "btcgate.json").write_text(json.dumps({"push": ["lock"]}))
  worker = Worker(tmp_path)
  assert worker.push == {"lock"} and "push" not in worker.settings  # nfiforge's key never reaches btcgate
  sent = []
  alerts = SimpleNamespace(coins={"ABC"}, cooldown=3600, alert=lambda *args: sent.append(args) or True)
  worker.engine = SimpleNamespace(alerts=alerts)
  worker.hook_alerts()
  alerts.alert("ABC/USDT:USDT", "lock", None, "delist")
  alerts.alert("ABC/USDT:USDT", "lock", None, "delist")  # inside the cooldown
  alerts.alert("XYZ/USDT:USDT", "catchup", 2.0)  # not on the coin list
  rows = [json.loads(line) for line in (tmp_path / "signals.jsonl").read_text().splitlines()]
  assert [(row["pair"], row["signal"], row["push"]) for row in rows] == [("ABC/USDT:USDT", "lock", True)]
  assert len(sent) == 3  # telegram still gets every call and applies its own rules


def test_status_written_from_many_threads(tmp_path):
  pytest.importorskip("btcgate")
  from concurrent.futures import ThreadPoolExecutor

  from nfiforge.btcgate.worker import write_json

  with ThreadPoolExecutor(8) as pool:  # the candle threads all report progress (one shared temp name crashed it)
    list(pool.map(lambda i: write_json(tmp_path / "status.json", {"i": i}), range(400)))
  assert "i" in json.loads((tmp_path / "status.json").read_text())
  assert not list(tmp_path.glob("*.tmp"))


def test_bot_pairs_map_to_binance():
  pytest.importorskip("btcgate")
  from nfiforge.btcgate.worker import bare, to_binance

  perps = {symbol: {} for symbol in ["BTC/USDT:USDT", "1000PEPE/USDT:USDT", "1000SHIB/USDT:USDT", "KAITO/USDT:USDT"]}
  assert bare("SHIB1000/USDT:USDT") == bare("1000SHIB/USDT:USDT") == "SHIB" and bare("1000/USDT:USDT") == "1000"
  found, missing = to_binance(
    ["PEPE/USDT:USDT", "SHIB1000/USDT:USDT", "KAITO/USDT:USDT", "NOPE/USDT:USDT", "kaito/usdt"], perps
  )
  assert found == ["1000PEPE/USDT:USDT", "1000SHIB/USDT:USDT", "KAITO/USDT:USDT"] and missing == ["NOPE"]


def test_coin_list_modes_add_open_trades(tmp_path):
  pytest.importorskip("btcgate")
  from nfiforge.btcgate.worker import Worker

  perps = {symbol: {} for symbol in ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "KAITO/USDT:USDT"]}
  worker = Worker(tmp_path)
  assert worker.mode == "full" and worker.settings["ledger"]["test_signals"] is True
  worker.perps, worker.picked = perps, ["BTC/USDT:USDT", "ETH/USDT:USDT"]
  assert worker.choose() and worker.coins == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
  assert not worker.choose()  # nothing new
  (tmp_path / "bot_coins.json").write_text(
    json.dumps({"whitelist": ["SOL/USDT:USDT"], "open": ["KAITO/USDT:USDT", "GONE/USDT:USDT"]})
  )
  assert worker.choose() and worker.coins == ["BTC/USDT:USDT", "ETH/USDT:USDT", "KAITO/USDT:USDT"]  # open trade added
  assert worker.status["extra"] == ["KAITO"] and worker.status["missing"] == ["GONE"]

  # bots' coins: whitelist + BTC + open trades, ledger off whatever the file says
  (tmp_path / "btcgate.json").write_text(json.dumps({"coins": "bots", "ledger": {"test_signals": True}}))
  worker = Worker(tmp_path)
  assert worker.mode == "bots" and worker.settings["ledger"]["test_signals"] is False and "coins" not in worker.settings
  worker.perps = perps
  worker.choose()
  assert worker.coins == ["BTC/USDT:USDT", "SOL/USDT:USDT", "KAITO/USDT:USDT"]


async def test_supervisor_shares_bot_coins_on_change(tmp_path):
  import asyncio

  from nfiforge.btcgate.supervisor import Supervisor

  coins = {"whitelist": ["A/USDT:USDT"], "open": []}
  gate = Supervisor(tmp_path, 4096, bot_coins=lambda: dict(coins))
  task = asyncio.create_task(gate._share("bot_coins.json", gate.bot_coins, every=0.05))
  await asyncio.sleep(0.1)
  path = tmp_path / "bot_coins.json"
  assert json.loads(path.read_text()) == coins
  mtime = path.stat().st_mtime_ns
  await asyncio.sleep(0.15)
  assert path.stat().st_mtime_ns == mtime  # unchanged: not rewritten
  coins["open"] = ["KAITO/USDT:USDT"]
  await asyncio.sleep(0.15)
  task.cancel()
  assert json.loads(path.read_text())["open"] == ["KAITO/USDT:USDT"]


def test_signals_list_last_30_days_with_bot_pairs(tmp_path):
  from datetime import UTC, datetime, timedelta

  from nfiforge.btcgate.routes import signals

  connection = sqlite3.connect(tmp_path / "btcgate_monitor.sqlite")
  connection.execute(
    "create table signals (date text, pair text, tag text, side int, price real, outcome text, ret real,"
    " mfe real, mae real)"
  )
  new, old = (str(datetime.now(UTC) - timedelta(days=days)) for days in (1, 40))
  connection.executemany(
    "insert into signals values (?,?,?,?,?,?,?,?,?)",
    [
      (new, "A/USDT:USDT", "core64", 1, 1.0, "tp", 0.04, 0.05, -0.01),
      (old, "B/USDT:USDT", "core64", 1, 1.0, "sl", -0.02, 0.0, -0.02),
    ],
  )
  connection.commit()
  connection.close()
  (tmp_path / "bot_coins.json").write_text(json.dumps({"whitelist": ["A/USDT:USDT"], "open": ["K/USDT:USDT"]}))
  out = signals(tmp_path)
  assert [row["pair"] for row in out["ledger"]] == ["A/USDT:USDT"] and out["ledger"][0]["ret_pct"] == pytest.approx(4)
  assert out["bot_pairs"] == ["A/USDT:USDT", "K/USDT:USDT"] and out["alerts"]["events"] == []


def test_alert_scoring_moves_and_usual_rate():
  pytest.importorskip("btcgate")
  import numpy as np
  import pandas as pd
  from nfiforge.btcgate.worker import score_events

  now = pd.Timestamp("2026-10-10 00:00", tz="UTC")
  dates = pd.date_range(now - pd.Timedelta(days=2), now, freq="5min")
  rising = pd.DataFrame({"date": dates, "close": np.linspace(100, 200, len(dates))})  # rises the whole time
  frames = {"UP/USDT:USDT": rising}
  signal_at = str(dates[100])
  rows = [
    (signal_at, "UP/USDT:USDT", "forced_dump", -4.0),  # says up: right
    (signal_at, "UP/USDT:USDT", "forced_squeeze", 4.0),  # says down: wrong
    (str(dates[-5]), "UP/USDT:USDT", "warn_absorb", 3.0),  # too new for 1 h
    (signal_at, "GONE/USDT:USDT", "dir_catchup", 3.0),  # no candles
  ]
  out = score_events(rows, lambda pair, timeframe: frames.get(pair, pd.DataFrame(columns=["date", "close"])), now)
  events = out["events"]
  assert events[0]["price"] == pytest.approx(rising["close"][100]) and events[0]["1h"] == pytest.approx(
    rising["close"][112] / rising["close"][100] - 1
  )
  assert events[2]["1h"] is None and events[3]["price"] is None
  dump, squeeze = out["summary"]["forced_dump"], out["summary"]["forced_squeeze"]
  assert dump["1h"]["right"] == 1.0 and dump["1h"]["usual"] == 1.0  # a coin going up anyway: no better than usual
  assert squeeze["1h"]["right"] == 0.0 and squeeze["1h"]["usual"] == 0.0
  assert "dir_catchup" not in out["summary"]  # nothing scorable


def test_book_per_bot_written_with_history_and_alert(tmp_path):
  pytest.importorskip("btcgate")
  from types import SimpleNamespace

  import numpy as np
  import pandas as pd
  from nfiforge.btcgate.routes import book
  from nfiforge.btcgate.worker import Worker

  worker = Worker(tmp_path)
  worker.perps = {symbol: {} for symbol in ["BTC/USDT:USDT", "ETH/USDT:USDT", "1000PEPE/USDT:USDT"]}
  worker.engine = SimpleNamespace(alerts=SimpleNamespace(on=False, signals=set()))
  worker.push, worker.book_alerts = {"book"}, {"max_swing_usd": 1, "min_bets": 0, "hours": 6}
  hours = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(hours=1), periods=740, freq="1h")
  rng = np.random.default_rng(1)
  common = rng.normal(0, 0.01, len(hours))
  for pair in ("BTC/USDT:USDT", "1000PEPE/USDT:USDT"):  # two coins that move together
    close = 100 * np.exp(np.cumsum(common + rng.normal(0, 0.002, len(hours))))
    worker.candles.frames[(pair, "1h")] = pd.DataFrame({"date": hours, "close": close})
  trade = {"amount": 1, "open_rate": 100, "current_rate": 100, "is_short": False, "stake_amount": 100, "leverage": 1}
  worker.books = {
    "Live": [
      {**trade, "pair": "BTC/USDT:USDT"},
      {**trade, "pair": "PEPE/USDT:USDT"},
      {**trade, "pair": "MNT/USDT:USDT"},
    ],
    "Idle": [],
  }
  worker.book()
  worker.book()  # the alert waits its 6 h
  live = json.loads((tmp_path / "book.json").read_text())["books"]["Live"]
  assert live["n"] == 3 and live["measured"] == 2 and live["unmeasured"] == ["MNT/USDT:USDT"]
  assert (
    1 <= live["eff"] < 1.3 and live["sd"] > live["naive_sd"]
  )  # together: about one bet, more swing than "independent"
  out = book(tmp_path)
  assert out["books"]["Idle"]["n"] == 0 and out["books"]["Idle"]["eff"] is None
  assert {row["bot"] for row in out["history"]} == {"Live", "Idle"} and len(out["history"]) == 2
  rows = [json.loads(line) for line in (tmp_path / "signals.jsonl").read_text().splitlines()]
  assert len(rows) == 1 and rows[0]["pair"] == "Live" and rows[0]["signal"] == "book" and rows[0]["push"] is True
  assert "likely 24h swing" in rows[0]["kind"]


def test_scanner_first_run_quiet_then_new_coins_alert_once(tmp_path):
  pytest.importorskip("btcgate")
  from types import SimpleNamespace

  import pandas as pd
  from nfiforge.btcgate.worker import BinanceFeed, Worker

  sent = []
  worker = Worker(tmp_path)
  assert worker.scan_on and worker.settings["scanner"]["enabled"] is False  # the engine never posts a scan itself
  flagged = [
    {
      "coin": "AAA",
      "pair": "AAA/USDT:USDT",
      "labels": ["PUMP"],
      "r24": 0.4,
      "spread": 0.5,
      "r7": None,
      "vol": 9e7,
      "rank": 3,
      "listed": True,
      "reasons": ["+40.0 % in 24h"],
      "known": [],
      "extras": [""],
    }
  ]
  recovery = [
    {"coin": "LSK", "pair": "LSK/USDT:USDT", "vol": 8e7, "r7": 0.1, "r30": 0.2, "checks": {}, "passed": 7},
    {"coin": "STX", "pair": "STX/USDT:USDT", "vol": 8e7, "r7": 0.1, "r30": 0.2, "checks": {}, "passed": 3},
  ]
  worker.engine = SimpleNamespace(
    alerts=SimpleNamespace(on=True, signals={"scanner"}, _send=sent.append),
    btcgate_scan_rows=lambda full: (list(flagged), pd.Timestamp.now(tz="UTC")),
    btcgate_recovery_rows=lambda: (5e7, recovery),
    btcgate_recovery=lambda: "recovery text",
  )
  worker.push = {"scanner"}
  signals = tmp_path / "signals.jsonl"
  state = {}
  worker.scan(state)  # first run: known, no alert
  assert not signals.exists() and not sent and "AAA|PUMP" in state["seen"] and state["primed"]
  flagged.append({**flagged[0], "coin": "BBB", "pair": "BBB/USDT:USDT", "labels": ["SLOW_BLEED"]})
  worker.scan(state)
  worker.scan(state)  # BBB already posted
  rows = [json.loads(line) for line in signals.read_text().splitlines()]
  assert [(row["pair"], row["signal"], row["kind"], row["push"]) for row in rows] == [
    ("BBB/USDT:USDT", "scanner", "SLOW_BLEED", True)
  ]
  assert len(sent) == 1 and "BBB" in sent[0] and "AAA" not in sent[0]
  assert [row["coin"] for row in json.loads((tmp_path / "scan.json").read_text())["rows"]] == ["AAA", "BBB"]
  # recovery: the page gets 6/8 and up
  worker.scan_t = worker.rec_t = 0
  worker.scan_tick()
  assert not worker.scan_busy  # no tickers yet: waits for the first pass
  worker.tickers = {"AAA/USDT:USDT": {}}
  worker.scan_tick()
  for _ in range(100):
    if not worker.scan_busy and (tmp_path / "recovery.json").exists():
      break
    import time

    time.sleep(0.05)
  assert [row["coin"] for row in json.loads((tmp_path / "recovery.json").read_text())["rows"]] == ["LSK"]
  # the feed: the bots' lists for "your pairlist" and the blacklist, /book from nfiforge's books
  worker.perps = {symbol: {} for symbol in ["BTC/USDT:USDT", "SOL/USDT:USDT"]}
  worker.coins, worker.bot_coins, worker.bot_blacklist = ["BTC/USDT:USDT"], (1, ["SOL/USDT:USDT"], []), ["(LSK|STX)/.*"]
  feed = BinanceFeed(worker)
  assert feed.pairlist() == ["SOL/USDT:USDT"] and "(LSK|STX)/.*" in feed.blacklist()
  worker.last_books = {"Live": {"n": 0}}
  assert "Live" in feed.book_report() and "no open trades" in feed.book_report()
