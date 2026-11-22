import asyncio
import time

import httpx
import pytest
from fake_freqtrade import PASSWORD, USER
from nfiforge.config import AppConfig, ConfigError, load_config
from nfiforge.connectors.freqtrade import BotConnector


def _cfg(url: str, password: str = PASSWORD) -> AppConfig:
  return AppConfig.model_validate(
    {
      "bots": [{"name": "Fake", "url": url, "username": USER, "password": password}],
      "update_check": False,
      "poll": {"status": 0.2, "health": 0.2, "balance": 0.2, "profit": 0.2, "whitelist": 0.2, "custom_data": 0.2},
    }
  )


TEST_PW = "test-password-123"


async def _signin(app, client, role="admin", name=None):
  from nfiforge.auth import hash_password

  name = name or f"t-{role}"
  if not app.state.db.user_by_name(name):
    app.state.db.add_user(name, hash_password(TEST_PW), role)
  response = await client.post("/api/auth/login", json={"username": name, "password": TEST_PW})
  assert response.status_code == 200, response.text


async def _wait(cond, timeout=5.0):
  end = time.time() + timeout
  while time.time() < end:
    if cond():
      return True
    await asyncio.sleep(0.05)
  return False


async def test_connector_reads_state_and_events(fake):
  app, url, _ = fake
  config = _cfg(url)
  published = []
  connector = BotConnector(config.bots[0], config.poll, published.append)
  await connector.start()
  try:
    assert await _wait(
      lambda: connector.state["connected"] and connector.state["balance"] and connector.state["custom_data"]
    )
    assert connector.state["is_nfi"] and connector.state["config"]["max_open_trades"] == 8
    assert connector.state["status"][0]["pair"] == "APE/USDT:USDT"
    assert await _wait(lambda: connector.state["ws_connected"])
    app.state.ws_queue.put_nowait({"type": "entry_fill", "data": {"pair": "SOL/USDT:USDT", "enter_tag": "12"}})
    assert await _wait(lambda: any(e["type"] == "entry_fill" for e in connector.events))
    assert any(message["type"] == "event" for message in published)
  finally:
    await connector.stop()


async def test_one_endpoint_error_clears_when_it_answers_again(fake):
  app, url, _ = fake
  config = _cfg(url)
  connector = BotConnector(config.bots[0], config.poll, lambda message: None)
  await connector.start()
  try:
    assert await _wait(lambda: connector.state["connected"] and connector.state["balance"])
    app.state.failing.add("/balance")
    assert await _wait(lambda: "/balance" in (connector.state["error"] or ""))
    # Then: still connected, the other endpoints answer
    assert connector.state["connected"]
    app.state.failing.clear()
    # Then: the stale error goes once /balance answers again
    assert await _wait(lambda: connector.state["error"] is None)
  finally:
    await connector.stop()


async def test_wrong_password_reports_clear_error(fake):
  _, url, _ = fake
  config = _cfg(url, password="wrong")
  connector = BotConnector(config.bots[0], config.poll, lambda message: None)
  await connector.start()
  try:
    assert await _wait(lambda: connector.state["error"] is not None)
    assert "rejected username/password" in connector.state["error"] and not connector.state["connected"]
  finally:
    await connector.stop()


async def test_app_api(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  transport = httpx.ASGITransport(app=app)
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://t") as client:
    await _signin(app, client)
    assert (await client.get("/api/health")).json()["ok"]
    assert await _wait(lambda: app.state.bots["Fake"].state["connected"])
    bots = (await client.get("/api/bots")).json()
    assert bots[0]["name"] == "Fake" and bots[0]["strategy"] == "NostalgiaForInfinityX8"
    assert (await client.get("/api/bots/Fake/state")).json()["config"]["exchange"] == "bybit"
    assert (await client.get("/api/bots/Nope/state")).status_code == 404


def test_config_errors_are_readable(tmp_path, monkeypatch):
  path = tmp_path / "c.yaml"
  path.write_text("host: 0.0.0.0\nbots:\n  - {name: A, url: ftp://x, username: u, password_env: NOPE_PW}\n")
  monkeypatch.delenv("NOPE_PW", raising=False)
  with pytest.raises(ConfigError) as e:
    load_config(path)
  assert "bots.0.url" in str(e.value) or "url" in str(e.value)
  with pytest.raises(ConfigError, match="not found"):
    load_config(tmp_path / "missing.yaml")


def test_host_list(monkeypatch):
  monkeypatch.setenv("PW", "x")
  config = AppConfig.model_validate(
    {
      "host": ["127.0.0.1", "100.64.0.1"],
      "bots": [{"name": "A", "url": "http://x", "username": "u", "password_env": "PW"}],
    }
  )
  assert config.hosts == ["127.0.0.1", "100.64.0.1"]


async def test_settings_persist(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  transport = httpx.ASGITransport(app=app)
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://t") as client:
    await _signin(app, client)
    settings = (await client.get("/api/settings")).json()
    assert settings["gauges"]["cpu"]["enabled"] and settings["gauges"]["stake_used"]["enabled"]
    settings["gauges"]["cpu"]["enabled"] = False
    settings["gauges"]["ram"]["warn"] = 60
    settings["gauges"]["cpu"]["style"] = "segment"
    settings["layouts"]["trading"] = {"items": [{"i": "status", "x": 0, "y": 0, "w": 12, "h": 2}], "hidden": ["events"]}
    assert (await client.put("/api/settings", json=settings)).status_code == 200
  again = create_app(config).state.settings.settings
  assert again.gauges["cpu"].enabled is False and again.gauges["ram"].warn == 60
  assert again.layouts["trading"]["hidden"] == ["events"]
  assert again.gauges["cpu"].style == "segment" and again.gauges["ram"].style is None


async def test_trading_page_data(fake, tmp_path):
  _, url, _ = fake
  config = _cfg(url)
  from nfiforge.store import Store

  db = Store(tmp_path)
  connector = BotConnector(config.bots[0], config.poll, lambda message: None, db)
  await connector.start()
  try:
    assert await _wait(
      lambda: connector.state["trades"] and connector.state["pulse"] and connector.state["pair_prices"], timeout=8
    )
    pair = connector.state["pulse"]
    assert pair["pair"] == "BTC/USDT:USDT" and len(pair["candles"]) == 288 and pair["rsi_4h"] is not None
    assert pair["change"]["1h"] > 0 and "APE/USDT:USDT" in connector.state["pair_prices"]
  finally:
    await connector.stop()
  db.add_equity("Fake", 1000, -5, timestamp=time.time())
  assert db.equity("Fake", 0)[-1]["equity"] == 995


def test_metrics_and_host():
  from nfiforge.connectors.host import HostMonitor
  from nfiforge.metrics import pct_change, rsi, wilson

  assert rsi([float(value) for value in range(30)]) == 100.0
  assert 40 < rsi([100 + (i % 2) for i in range(60)]) < 60
  assert pct_change([100.0, 110.0], 1) == pytest.approx(10.0)
  low, high = wilson(19, 20)
  assert 0.75 < low < 0.95 and high == pytest.approx(0.99, abs=0.02)
  sample = HostMonitor(lambda message: None).sample()
  assert 0 <= sample["cpu"] <= 100 and 0 <= sample["ram"] <= 100 and sample["load"] >= 0


async def test_serves_built_ui(fake, tmp_path, monkeypatch):
  _, url, _ = fake
  from nfiforge.app import create_app

  (tmp_path / "assets").mkdir()
  (tmp_path / "index.html").write_text("<title>NFIForge vX</title>")
  (tmp_path / "assets" / "a.js").write_text("ok")
  monkeypatch.setenv("NFIFORGE_WEB", str(tmp_path))
  config = _cfg(url)
  config.data_dir = str(tmp_path / "data")
  app = create_app(config)
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
    await _signin(app, client)
    assert "NFIForge" in (await client.get("/trading")).text  # spa route falls back to index.html
    assert (await client.get("/assets/a.js")).text == "ok"
    assert (await client.get("/api/bots")).status_code == 200  # api still wins (signed in above)
    assert (await client.get("/../../etc/passwd")).text.startswith("<title>")  # no path escape


async def test_update_check_and_schema(tmp_path, monkeypatch):
  from nfiforge import updates
  from nfiforge.store import Store

  assert updates._ver("v0.10.1") > updates._ver("0.9.9")
  off = await updates.check(enabled=False)
  assert off["latest"] is None and off["newer"] is False
  monkeypatch.setitem(updates._cache, updates.REPO, (9e12, {"tag_name": "v99.0.0", "html_url": "https://x/rel"}))
  update = await updates.check()
  assert update["newer"] and update["latest"] == "99.0.0"
  db = Store(tmp_path)
  assert db.schema_version() == len(Store.MIGRATIONS)
  assert Store(tmp_path).schema_version() == len(Store.MIGRATIONS)  # reopening does not re-run


async def test_history_and_timeframe(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app
  from nfiforge.connectors.market import pick_timeframe

  assert pick_timeframe(3600)[0] == "5m" and pick_timeframe(5 * 86400)[0] == "15m"
  assert pick_timeframe(30 * 86400)[0] == "1h" and pick_timeframe(400 * 86400)[0] == "1d"
  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  transport = httpx.ASGITransport(app=app)
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://t") as client:
    await _signin(app, client)
    assert await _wait(lambda: app.state.bots["Fake"].history, timeout=8)
    history = (await client.get("/api/bots/Fake/history")).json()
    assert history[0]["trade_id"] == 9 and history[0]["exit_reason"] == "roi"
    assert app.state.bots["Fake"].state["trades"]["total"] == 1


async def test_frame_columns_plot_config(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  transport = httpx.ASGITransport(app=app)
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://t") as client:
    await _signin(app, client)
    assert await _wait(lambda: app.state.bots["Fake"].state["config"], timeout=8)
    cols = (await client.get("/api/bots/Fake/frame/columns", params={"pair": "BTC/USDT:USDT"})).json()
    assert cols[:2] == ["ema_50", "rsi_14"]
    params = {"pair": "BTC/USDT:USDT", "columns": "ema_50", "limit": 10}
    frame = (await client.get("/api/bots/Fake/frame", params=params)).json()
    assert frame["columns"][-1] == "ema_50" and "__date_ts" in frame["columns"] and len(frame["data"]) == 10
    plot_config = (await client.get("/api/bots/Fake/plot_config")).json()
    assert "ema_50" in plot_config["main_plot"] and "RSI" in plot_config["subplots"]
    assert await _wait(lambda: app.state.bots["Fake"].logs_kept, timeout=8)
    logs = (await client.get("/api/bots/Fake/logs")).json()
    assert len(logs["logs"]) == 4 and logs["logs"][2][3] == "WARNING" and logs["warning"] is None
    assert "eyJ" not in logs["logs"][0][4] and "token=•••" in logs["logs"][0][4]
    await asyncio.sleep(3.5)  # the next poll returns the same lines: nothing duplicated
    assert len((await client.get("/api/bots/Fake/logs")).json()["logs"]) == 4
    await _wait(lambda: app.state.bots["Fake"].state["locks"], timeout=8)
    health = (await client.get("/api/bots/Fake/checks")).json()
    keys = {check["key"]: check["level"] for check in health["checks"]}
    assert health["config"]["exchange"] == "bybit" and keys["mode"] == "ok" and keys["locks"] == "info"
    bot = app.state.bots["Fake"]
    await _wait(lambda: bot.state["blacklist"], timeout=8)
    bot._set("whitelist", {"whitelist": ["BTC/USDT:USDT"]})  # ETH dropped by the age filter
    pairs = (await client.get("/api/bots/Fake/pairs")).json()
    assert pairs["blacklist"] == ["(LAVA)/.*"] and pairs["locks"][0]["pair"] == "ETH/USDT:USDT"
    assert pairs["filtered"][0]["filter"] == "AgeFilter" and "age 3" in pairs["filtered"][0]["reason"]
    assert pairs["changes"][0]["change"] == "removed" and pairs["changes"][0]["pair"] == "ETH/USDT:USDT"
    # freqtrade's real shape: fields at the top level, not under "data"
    bot._on_ws_message(
      {
        "type": "exit_fill",
        "pair": "ETH/USDT:USDT",
        "direction": "Long",
        "profit_ratio": 0.02,
        "profit_amount": 2.1,
        "exit_reason": "roi",
        "is_final_exit": True,
      }
    )
    notes = (await client.get("/api/notifications")).json()
    assert notes["items"][0]["kind"] == "trade" and notes["unread"] >= 1
    assert notes["items"][0]["title"] == "ETH/USDT:USDT long closed +2.00 %" and "roi" in notes["items"][0]["detail"]
    assert (await client.post("/api/notifications/read", json={"id": notes["items"][0]["id"]})).json()["unread"] == 0
    assert "eyJ" not in logs["logs"][0][4] and "token=•••" in logs["logs"][0][4]


def test_health_checks():
  from nfiforge.health import checks

  now = time.time()
  live = {
    "connected": True,
    "ws_connected": False,
    "latency_ms": 40,
    "version": "2026.8",
    "health": {"last_process_ts": now - 900},
    "locks": {"lock_count": 2},
    "config": {
      "state": "running",
      "dry_run": False,
      "exchange": "bybit",
      "trading_mode": "futures",
      "margin_mode": "cross",
      "stoploss": -0.99,
      "stoploss_on_exchange": False,
      "force_entry_enable": True,
      "stake_amount": "unlimited",
      "max_open_trades": 8.0,
    },
  }
  got = {check["key"]: check["level"] for check in checks(live, logs_debug=True, logs_missed=False, ft_latest="2026.9")}
  assert got["ws"] == "warn" and got["loop"] == "bad" and got["mode"] == "info" and got["margin"] == "warn"
  assert (
    got["sl_exchange"] == "info" and got["debug"] == "warn" and got["ft_version"] == "info" and got["locks"] == "info"
  )
  live["config"]["stoploss"] = -0.1  # a normal stop, not on the exchange: worth fixing
  assert {check["key"]: check["level"] for check in checks(live, False, False, None)}["sl_exchange"] == "warn"
  live["config"].update(dry_run=True, margin_mode="isolated", force_entry_enable=False)
  live.update(ws_connected=True, version="2026.9", health={"last_process_ts": now - 5}, locks={})
  got = {check["key"]: check["level"] for check in checks(live, False, False, "2026.9")}
  assert set(got.values()) == {"ok"} and "sl_exchange" not in got
  assert checks({"connected": False, "error": "down"}, False, False, None)[0]["level"] == "bad"


def test_alerts_raise_and_clear(tmp_path):
  from types import SimpleNamespace

  from nfiforge.alerts import Notifier, describe
  from nfiforge.settings import AlertSettings
  from nfiforge.store import Store

  db = Store(tmp_path)
  sent: list[dict] = []
  notifier = Notifier(db, lambda: AlertSettings(), lambda message: sent.append(message["data"]))
  bot = SimpleNamespace(state={"connected": False, "error": "refused"})
  notifier.check({"B": bot}, now=1000)
  assert not sent  # api down must hold 60 s first
  notifier.check({"B": bot}, now=1061)
  assert sent[-1]["level"] == "bad" and sent[-1]["key"] == "api" and db.unread() == 1
  trade = {"trade_id": 7, "pair": "APE/USDT:USDT", "is_short": False, "current_rate": 1.0, "liquidation_price": 0.9}
  bot.state = {"connected": True, "ws_connected": True, "status": [trade], "health": {"last_process_ts": 1100}}
  notifier.check({"B": bot}, now=1100)
  titles = [note["title"] for note in sent]
  assert "Resolved: B: bot API not reachable" in titles and any("10.0 % from liquidation" in title for title in titles)
  assert [note_row["key"] for note_row in db.notes(active=True)] == ["liq:7"]
  assert Notifier(db, lambda: AlertSettings(), sent.append).active  # still open after a restart
  assert (
    describe("exit_fill", {"pair": "X", "direction": "Long", "profit_ratio": -0.02, "exit_reason": "stop"})[0] == "warn"
  )
  assert "opened" in describe("entry_fill", {"pair": "X", "direction": "Long", "leverage": 3, "enter_tag": "12"})[1]
  db.set_read(db.notes(1)[0]["id"])
  assert db.unread() == 0


def _fake_host(root, container_id, mem, start_ticks, argvs):
  scope = root / "sys/fs/cgroup/system.slice" / f"docker-{container_id}.scope"
  scope.mkdir(parents=True, exist_ok=True)
  (scope / "memory.current").write_text(f"{mem}\n")
  (scope / "memory.max").write_text("1000\n")
  (scope / "memory.events").write_text("low 0\noom_kill 0\n")
  (scope / "cpu.stat").write_text("usage_usec 5000000\n")
  (root / "proc").mkdir(exist_ok=True)
  (root / "proc/stat").write_text("cpu 1 2 3\nbtime 1700000000\n")
  for pid, argv in argvs.items():
    proc_dir = root / "proc" / str(pid)
    proc_dir.mkdir(exist_ok=True)
    (proc_dir / "cgroup").write_text(f"0::/system.slice/docker-{container_id}.scope\n")
    rest = " ".join(["S"] + ["0"] * 18 + [str(start_ticks + pid)])
    (proc_dir / "stat").write_text(f"{pid} (x) {rest}\n")
    (proc_dir / "cmdline").write_text("\0".join(argv) + "\0")


def test_containers_and_server_alerts(tmp_path):
  from nfiforge.alerts import Notifier
  from nfiforge.connectors.containers import ContainerMonitor, label
  from nfiforge.settings import AlertSettings
  from nfiforge.store import Store

  assert label(["/bin/app", "--password", "hunter2"]) == "app"
  argv = [
    "/usr/bin/python3",
    "/home/ftuser/.local/bin/freqtrade",
    "trade",
    "--config",
    "/u/config_live.json",
    "-s",
    "X8",
  ]
  assert label(argv) == "freqtrade trade · X8 · config_live.json"
  container_id = "ab" * 32
  _fake_host(tmp_path, container_id, 950, 100, {1: ["sleep", "infinity"], 2: argv})
  monitor = ContainerMonitor(str(tmp_path))
  container = monitor.sample()["abababababab"]
  assert (
    container["label"].startswith("freqtrade trade")
    and container["mem"] == 950
    and container["mem_max"] == 1000
    and container["restarts"] == 0
  )
  _fake_host(tmp_path, container_id, 950, 500, {1: ["sleep", "infinity"], 2: argv})  # main process started again
  monitor._procs_at = 0
  assert monitor.sample()["abababababab"]["restarts"] == 1

  db = Store(tmp_path / "data")
  sent: list[dict] = []
  notifier = Notifier(db, lambda: AlertSettings(), lambda msg: sent.append(msg["data"]))
  host = {"disk": 97, "disk_free": 2**30, "ram": 50, "containers": list(monitor.state.values())}
  notifier.check({}, host, now=1000)
  keys = {note["key"] for note in sent}
  assert {"disk", "cmem:abababababab"} <= keys
  host["containers"] = [{**host["containers"][0], "oom_kills": 1}]
  notifier.check({}, host, now=1010)
  assert any(note["key"] == "oom:abababababab" and note["level"] == "bad" for note in sent)
  db.add_server({"cpu": 10, "ram": 50, "containers": host["containers"]}, {"Live": 6.0})
  history = db.server_history(0)
  assert (
    history["host"][0]["ram"] == 50
    and history["containers"][0]["id"] == "abababababab"
    and history["loops"][0]["loop_s"] == 6.0
  )


async def test_manage_bots(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  local = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
  remote = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("192.168.1.9", 5)), base_url="http://t")
  async with app.router.lifespan_context(app), local as client, remote as remote_client:
    await _signin(app, client)
    await _signin(app, remote_client)
    listing = (await client.get("/api/manage/bots")).json()
    assert (
      listing["why_not"] is None and listing["bots"][0]["source"] == "config" and "password" not in listing["bots"][0]
    )
    assert "this machine" in (await remote_client.get("/api/manage/bots")).json()["why_not"]
    new = {"name": "Fake 2", "url": url, "username": USER, "password": PASSWORD}
    assert (await remote_client.post("/api/manage/bots", json=new)).status_code == 403
    assert (await client.post("/api/manage/bots/test", json={**new, "password": "nope"})).json()["ok"] is False
    assert (await client.post("/api/manage/bots/test", json=new)).json()["ok"] is True
    assert (await client.post("/api/manage/bots", json=new)).status_code == 200
    assert (await client.post("/api/manage/bots", json=new)).status_code == 409
    assert await _wait(lambda: app.state.bots["Fake 2"].state["connected"], timeout=8)
    assert oct((tmp_path / "bots.json").stat().st_mode & 0o777) == "0o600"
    assert (await client.put("/api/manage/bots/Fake", json={**new, "name": "Fake"})).status_code == 403  # config bot
    response = await client.put(
      "/api/manage/bots/Fake 2", json={"name": "Dry", "url": url, "username": USER}
    )  # keeps password
    assert response.status_code == 200 and "Dry" in app.state.bots and "Fake 2" not in app.state.bots
    assert await _wait(lambda: app.state.bots["Dry"].state["connected"], timeout=8)
    # trading switch is saved per bot, but stays off in the browser while write_actions is off
    response = await client.put(
      "/api/manage/bots/Dry", json={"name": "Dry", "url": url, "username": USER, "trading": True}
    )
    assert (
      response.status_code == 200 and app.state.bots["Dry"].bot.trading and not app.state.bots["Dry"].state["trading"]
    )
    assert '"trading": true' in (tmp_path / "bots.json").read_text()
    assert (await client.delete("/api/manage/bots/Dry")).status_code == 200 and "Dry" not in app.state.bots
    assert [bot["name"] for bot in (await client.get("/api/manage/bots")).json()["bots"]] == ["Fake"]


async def test_phone_pairing(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app
  from nfiforge.auth import hash_password, new_secret

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  db = app.state.db
  user_id = db.add_user("phone", hash_password(TEST_PW), "viewer")
  code, code_hash = new_secret()
  db.add_pair(code_hash, user_id, 10)
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
    assert (await client.get("/api/bots")).status_code == 401
    assert (await client.post("/api/auth/pair", json={"code": "wrong"})).status_code == 403
    response = await client.post("/api/auth/pair", json={"code": code})
    assert (
      response.status_code == 200
      and response.json()["username"] == "phone"
      and "httponly" in response.headers["set-cookie"].lower()
    )
    assert (await client.get("/api/bots")).status_code == 200  # signed in by the code
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as other:
    assert (await other.post("/api/auth/pair", json={"code": code})).status_code == 403  # works once
    old, old_hash = new_secret()
    db.add_pair(old_hash, user_id, -1)  # expired
    assert (await other.post("/api/auth/pair", json={"code": old})).status_code == 403


async def test_accounts(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app
  from nfiforge.auth import hash_password, verify_password

  assert verify_password("hunter2-long", hash_password("hunter2-long")) and not verify_password("x", hash_password("y"))
  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  db = app.state.db
  stored = db.user_by_id(db.add_user("boss", hash_password(TEST_PW), "admin"))
  assert TEST_PW not in stored["pw"] and stored["pw"].startswith("scrypt$")
  transport = httpx.ASGITransport(app=app)
  async with (
    httpx.AsyncClient(transport=transport, base_url="http://t") as client,
    httpx.AsyncClient(transport=transport, base_url="http://t") as viewer,
  ):
    assert (await client.get("/api/settings")).status_code == 401
    assert (await client.get("/api/auth/status")).json() == {"has_users": True, "user": None}
    assert (await client.post("/api/auth/login", json={"username": "boss", "password": "nope"})).status_code == 401
    assert (await client.post("/api/auth/login", json={"username": "ghost", "password": "nope"})).status_code == 401
    assert (
      await client.post("/api/auth/login", content="x", headers={"content-type": "text/plain"})
    ).status_code == 415
    await _signin(app, client, name="boss")
    # admin makes a viewer
    response = await client.post("/api/users", json={"username": "watcher", "password": "short", "role": "viewer"})
    assert response.status_code == 422
    response = await client.post("/api/users", json={"username": "watcher", "password": TEST_PW, "role": "viewer"})
    assert response.status_code == 200 and response.json()["role"] == "viewer"
    await _signin(app, viewer, name="watcher")
    assert (await viewer.get("/api/settings")).status_code == 200  # viewers look
    settings = (await viewer.get("/api/settings")).json()
    assert (await viewer.put("/api/settings", json=settings)).status_code == 403  # but don't change
    assert (await viewer.get("/api/users")).status_code == 403
    assert (await viewer.get("/api/manage/bots")).status_code == 403
    # last admin can't go
    boss = db.user_by_name("boss")["id"]
    assert (await client.put(f"/api/users/{boss}", json={"role": "viewer"})).status_code == 409
    assert (await client.delete(f"/api/users/{boss}")).status_code == 409
    # password change signs other devices out
    watcher = db.user_by_name("watcher")["id"]
    assert (await client.put(f"/api/users/{watcher}", json={"password": "new-password-456"})).status_code == 200
    assert (await viewer.get("/api/bots")).status_code == 401
    assert (await client.post("/api/auth/logout", json={})).status_code == 200
    assert (await client.get("/api/bots")).status_code == 401
  # too many wrong passwords from one address: wait
  async with httpx.AsyncClient(transport=transport, base_url="http://t") as bad:
    codes = [
      (await bad.post("/api/auth/login", json={"username": "boss", "password": f"x{i}"})).status_code for i in range(6)
    ]
    assert codes[-1] == 429


def test_config_paths_and_reachable(tmp_path, monkeypatch):
  from nfiforge import setup
  from nfiforge.config import load_config

  config_path = tmp_path / "conf" / "config.yaml"
  config_path.parent.mkdir()
  config_path.write_text("host: [127.0.0.1, 100.64.0.9]\ndata_dir: ./d\n")
  monkeypatch.chdir(tmp_path)
  config = load_config(config_path)
  # relative data_dir sits next to the config, not where nfiforge was started
  assert config.data_dir == str(tmp_path / "conf" / "d")
  monkeypatch.setattr(setup, "tailscale_ip", lambda: "100.64.0.9")
  monkeypatch.setattr(setup, "lan_ip", lambda: "192.168.1.5")
  assert setup.reachable(config) == ["100.64.0.9"]
  config.host = "0.0.0.0"
  assert setup.reachable(config) == ["100.64.0.9", "192.168.1.5"]
  config.host = "127.0.0.1"
  assert setup.reachable(config) == []


def test_serve_urls(monkeypatch):
  import subprocess

  from nfiforge import setup

  out = """{"Web": {"pc.tail1.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8880"}}},
                     "pc.tail1.ts.net:443": {"Handlers": {"/": {"Proxy": "localhost:8880"}}},
                     "pc.tail1.ts.net:9443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}}}"""
  monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, out, ""))
  assert setup.serve_urls(8880) == ["https://pc.tail1.ts.net:8443", "https://pc.tail1.ts.net"]
  monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "no serve"))
  assert setup.serve_urls(8880) == []

  def missing(*args, **kwargs):
    raise FileNotFoundError("tailscale")

  monkeypatch.setattr(subprocess, "run", missing)
  assert setup.serve_urls(8880) == []


async def test_trade_actions(fake, tmp_path):
  fake_bot, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  async with (
    app.router.lifespan_context(app),
    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as viewer,
  ):
    await _signin(app, client)
    await _signin(app, viewer, role="viewer")
    enter = {"pair": "BTC/USDT:USDT", "side": "long", "stakeamount": 50}
    # viewers never; admins only with write_actions and the bot's own switch
    assert (await viewer.post("/api/trade/Fake/enter", json=enter)).status_code == 403
    assert "write_actions" in (await client.post("/api/trade/Fake/enter", json=enter)).json()["detail"]
    config.write_actions = True
    assert "Manage Bots" in (await client.post("/api/trade/Fake/enter", json=enter)).json()["detail"]
    app.state.bots["Fake"].bot.trading = True
    assert fake_bot.state.calls == []

    # dry bot: no typing needed; tag defaults to force_entry, blanks are left out
    response = await client.post("/api/trade/Fake/enter", json={**enter, "price": "", "ordertype": None})
    assert response.status_code == 200, response.text
    assert fake_bot.state.calls[-1] == (
      "forceenter",
      {"pair": "BTC/USDT:USDT", "side": "long", "entry_tag": "force_entry", "stakeamount": 50.0},
    )
    # grind add on the open trade keeps its tag
    response = await client.post(
      "/api/trade/Fake/enter",
      json={"pair": "APE/USDT:USDT", "side": "long", "entry_tag": "grind_2_entry", "stakeamount": 20},
    )
    assert response.status_code == 200 and fake_bot.state.calls[-1][1]["entry_tag"] == "grind_2_entry"
    # an add without a stake would get a whole trade's stake: refused
    await _wait(lambda: app.state.bots["Fake"].state["status"], timeout=5)
    response = await client.post(
      "/api/trade/Fake/enter", json={"pair": "APE/USDT:USDT", "side": "long", "entry_tag": "grind_1_entry"}
    )
    assert response.status_code == 422 and "give a stake" in response.json()["detail"]
    # bad input never reaches the bot
    calls_before = len(fake_bot.state.calls)
    for bad in (
      {**enter, "side": "up"},
      {**enter, "stakeamount": -5},
      {**enter, "ordertype": "stop"},
      {"side": "long"},
    ):
      assert (await client.post("/api/trade/Fake/enter", json=bad)).status_code == 422
    assert len(fake_bot.state.calls) == calls_before
    # freqtrade's 200-with-error answer is a failure
    response = await client.post("/api/trade/Fake/enter", json={**enter, "pair": "NOPE/USDT:USDT"})
    assert response.status_code == 502 and "Error entering" in response.json()["detail"]

    # partial exit; an amount at or above the whole trade is a full exit
    response = await client.post("/api/trade/Fake/exit", json={"tradeid": 1, "amount": 3000, "ordertype": "market"})
    assert response.status_code == 200 and fake_bot.state.calls[-1] == (
      "forceexit",
      {"tradeid": "1", "ordertype": "market", "amount": 3000.0},
    )
    await client.post("/api/trade/Fake/exit", json={"tradeid": 1, "amount": 99999})
    assert fake_bot.state.calls[-1] == ("forceexit", {"tradeid": "1"})
    assert (await client.post("/api/trade/Fake/exit", json={"tradeid": 9})).status_code == 409  # closed
    assert (await client.post("/api/trade/Fake/exit", json={"tradeid": 5})).status_code == 404
    assert (await client.post("/api/trade/Fake/reload", json={"tradeid": 1})).status_code == 200
    response = await client.post("/api/trade/Fake/cancel", json={"tradeid": 1})
    assert response.status_code == 502 and "No open order" in response.json()["detail"]

    # live bot: the pair (or coin) has to be typed back, checked fresh from the bot
    fake_bot.state.data["/show_config"]["dry_run"] = False
    calls_before = len(fake_bot.state.calls)
    response = await client.post("/api/trade/Fake/delete", json={"tradeid": 1})
    assert response.status_code == 428 and "type APE" in response.json()["detail"]
    assert (await client.post("/api/trade/Fake/delete", json={"tradeid": 1, "confirm": "BTC"})).status_code == 428
    assert len(fake_bot.state.calls) == calls_before
    assert (await client.post("/api/trade/Fake/delete", json={"tradeid": 1, "confirm": " ape "})).status_code == 200
    assert fake_bot.state.calls[-1] == ("delete", 1)

    # every action is in the notifications, with who did it
    notes = app.state.db.notes(100, kind="action")
    assert len(notes) == 8 and notes[0]["title"] == "t-admin: delete trade APE/USDT:USDT (live)"
    assert sum(lock["level"] == "bad" for lock in notes) == 2

    # bot control: live bot needs the bot's name typed back; state shows straight away
    assert (await client.post("/api/trade/Fake/control", json={"action": "shutdown"})).status_code == 422
    response = await client.post("/api/trade/Fake/control", json={"action": "pause", "confirm": "APE"})
    assert response.status_code == 428 and "type Fake" in response.json()["detail"]
    response = await client.post("/api/trade/Fake/control", json={"action": "pause", "confirm": "fake"})
    assert response.status_code == 200 and fake_bot.state.calls[-1] == ("pause", None)
    assert app.state.bots["Fake"].state["config"]["state"] == "paused"
    assert (await viewer.post("/api/trade/Fake/control", json={"action": "start"})).status_code == 403
    assert app.state.db.notes(1, kind="action")[0]["title"] == "t-admin: pause entries (live)"

    # locks + blacklist (still live: coin typed, the bot's name for "*"); the bot's answer shows straight away
    fake_bot.state.data["/show_config"]["dry_run"] = True
    assert (await client.post("/api/trade/Fake/lock", json={"pair": "SOL/USDT:USDT", "minutes": 0})).status_code == 422
    response = await client.post("/api/trade/Fake/lock", json={"pair": "SOL/USDT:USDT", "minutes": 90, "side": "long"})
    assert response.status_code == 200 and fake_bot.state.calls[-1][0] == "locks"
    sent = fake_bot.state.calls[-1][1][0]
    assert sent["pair"] == "SOL/USDT:USDT" and sent["side"] == "long" and sent["reason"] == "locked from NFIForge"
    locks = app.state.bots["Fake"].state["locks"]["locks"]
    assert [lock["pair"] for lock in locks] == ["ETH/USDT:USDT", "SOL/USDT:USDT"]
    assert (await client.post("/api/trade/Fake/unlock", json={"lockid": 99})).status_code == 404
    assert (await client.post("/api/trade/Fake/unlock", json={"lockid": 1})).status_code == 200
    assert [lock["pair"] for lock in app.state.bots["Fake"].state["locks"]["locks"]] == ["SOL/USDT:USDT"]
    fake_bot.state.data["/show_config"]["dry_run"] = False
    response = await client.post("/api/trade/Fake/lock", json={"pair": "*", "minutes": 5, "confirm": "SOL"})
    assert response.status_code == 428 and "type Fake" in response.json()["detail"]
    response = await client.post(
      "/api/trade/Fake/blacklist", json={"pair": "DOGE/USDT:USDT", "action": "add", "confirm": "doge"}
    )
    assert response.status_code == 200 and "DOGE/USDT:USDT" in app.state.bots["Fake"].state["blacklist"]["blacklist"]
    response = await client.post(
      "/api/trade/Fake/blacklist", json={"pair": "DOGE/USDT:USDT", "action": "add", "confirm": "DOGE"}
    )
    assert response.status_code == 502 and "already in pairlist" in response.json()["detail"]
    lava = {"pair": "(LAVA)/.*", "action": "remove"}
    response = await client.post("/api/trade/Fake/blacklist", json={**lava, "confirm": "(LAVA)/.*"})
    assert response.status_code == 200 and fake_bot.state.calls[-1] == ("unblacklist", ["(LAVA)/.*"])
    assert app.state.bots["Fake"].state["blacklist"]["blacklist"] == ["DOGE/USDT:USDT"]
    response = await client.post("/api/trade/Fake/blacklist", json={**lava, "confirm": "x"})
    assert response.status_code == 404
    assert (await viewer.post("/api/trade/Fake/lock", json={"pair": "A/B", "minutes": 5})).status_code == 403


async def test_ticker(fake, tmp_path, monkeypatch):
  _, url, _ = fake
  from nfiforge.app import create_app
  from nfiforge.connectors.market import CandleSource

  calls = []

  class Ex:
    async def fetch_ticker(self, pair):
      calls.append(pair)
      return {"last": 0.1645, "bid": 0.1644, "ask": 0.1646, "timestamp": None}

  monkeypatch.setattr(CandleSource, "_exchange", lambda self, name, futures: Ex())
  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  async with (
    app.router.lifespan_context(app),
    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
  ):
    await _signin(app, client, role="viewer")
    assert await _wait(lambda: app.state.bots["Fake"].state["config"], timeout=5)
    response = (await client.get("/api/bots/Fake/ticker", params={"pair": "APE/USDT:USDT"})).json()
    assert (
      response["last"] == 0.1645 and response["ask"] == 0.1646 and abs(response["ts"] - time.time()) < 5
    )  # no exchange time: now
    await client.get("/api/bots/Fake/ticker", params={"pair": "APE/USDT:USDT"})
    assert len(calls) <= 2  # shared for 2 s


async def test_excursions(fake, tmp_path, monkeypatch):
  _, url, _ = fake
  from nfiforge.app import create_app
  from nfiforge.connectors.market import CandleSource
  from nfiforge.excursions import measure

  # long from 100: high 110, low 95 -> mfe +10, mae -5; short mirrors; candles outside the trade don't count
  trade = {"open_timestamp": 1000_000, "close_timestamp": 4000_000, "open_rate": 100.0}
  candles = [[0, 0, 200, 1, 0], [1000_000, 0, 110, 95, 0], [3600_000, 0, 104, 99, 0], [4200_000, 0, 300, 2, 0]]
  assert measure(trade, candles, 60) == pytest.approx((10.0, -5.0))
  assert measure({**trade, "is_short": True}, candles, 60) == pytest.approx((5.0, -10.0))
  assert measure(trade, [], 60) is None
  # a trade inside one candle is measured from the candle it opened in
  assert measure(
    {**trade, "open_timestamp": 1000_030_000 // 1000, "close_timestamp": 1000_046}, [[1000_000, 0, 101, 99, 0]], 60
  )

  async def trade_candles(self, exchange, futures, pair, start, end):
    if pair.startswith("GONE"):
      import ccxt

      raise ccxt.BadSymbol("gone")
    return "1m", 60, candles

  monkeypatch.setattr(CandleSource, "trade_candles", trade_candles)
  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  async with (
    app.router.lifespan_context(app),
    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
  ):
    await _signin(app, client, role="viewer")
    bot = app.state.bots["Fake"]
    assert await _wait(lambda: bot.state["config"] and bot.history, timeout=8)
    bot.history[50] = {**trade, "trade_id": 50, "pair": "GONE/USDT:USDT", "is_open": False}
    bot.history[51] = {**trade, "trade_id": 51, "pair": "OK/USDT:USDT", "is_open": False}
    from nfiforge.excursions import Excursions

    await Excursions(app.state.db, CandleSource(), app.state.bots)._bot("Fake", 0)
    result = (await client.get("/api/bots/Fake/excursions")).json()
    assert (
      result["done"] == result["total"] == sum(1 for trade_row in bot.history.values() if not trade_row.get("is_open"))
    )
    assert result["rows"]["50"] == [None, None]  # delisted: marked, not retried
    assert result["rows"]["51"] == pytest.approx([10.0, -5.0])


def test_radar_outcomes():
  from nfiforge.radar import GUARDS, Radar

  radar, seconds, now = Radar(), 300, 1_791_000_000.0
  start = now - 20 * seconds
  cols = ["__date_ts", "enter_long", "enter_short", "enter_tag", *GUARDS]

  def frame(rows):
    return {
      "columns": cols,
      "data": [[timestamp * 1000, long, short, tag, *guards] for timestamp, long, short, tag, guards in rows],
    }

  ok = [True] * len(GUARDS)
  radar.add("A/USDT", frame([(start, 1, 0, "12 ", ok), (start + seconds, 0, 0, None, ok)]))  # traded
  radar.add("B/USDT", frame([(start, 1, 0, "12", ok)]))  # already in a trade
  radar.add("C/USDT", frame([(start, 1, 0, "12", ok)]))  # nfi cancelled it
  radar.add("D/USDT", frame([(start, 0, 1, "512", ok)]))  # slots full
  radar.add("E/USDT", frame([(start, 1, 0, "12", ok)]))  # no reason
  radar.add("F/USDT", frame([(now - seconds, 1, 0, "12", ok)]))  # this candle: pending
  radar.add("G/USDT", frame([(start, 0, 0, None, [False] + ok[1:])]))  # long guard off, no signal
  radar.prune([], now)

  def ms(seconds_value):
    return seconds_value * 1000

  trades = [
    {"trade_id": 1, "pair": "A/USDT", "is_short": False, "open_timestamp": ms(start + seconds + 5)},
    {"trade_id": 2, "pair": "B/USDT", "open_timestamp": ms(start - 3600), "close_timestamp": None},
    {"trade_id": 3, "pair": "X/USDT", "open_timestamp": ms(start - 3600), "close_timestamp": ms(now)},
  ]
  logs = [["", start + seconds + 10, "NFI", "INFO", "[x] Cancelling entry for C/USDT due to insufficient free slots."]]
  state = {"config": {"timeframe": "5m", "max_open_trades": 3}, "locks": {"locks": []}}
  view = radar.view(state, trades, logs, now)
  got = {pair: (cells[0][3], cells[0][4]) for pair, cells in view["pairs"].items()}
  assert got["A/USDT"] == ("traded", "")
  assert got["B/USDT"][1] == "already in a trade on this pair"
  assert got["C/USDT"] == ("blocked", "strategy: insufficient free slots")
  assert got["E/USDT"][0] == "not taken" and got["F/USDT"][0] == "pending"
  assert got["D/USDT"][0] == "not taken"  # 2 open of 3: not full
  state["config"]["max_open_trades"] = 2.0  # freqtrade sends a float
  assert radar.view(state, trades, logs, now)["pairs"]["D/USDT"][0][3:5] == ["blocked", "all 2 slots full"]
  # freqtrade's own refusals: low balance, an entry order that never filled (a long exit's cancel doesn't count)
  low = "Unable to create trade for E/USDT: Available balance (5.1 USDT) is lower than stake amount (85.0 USDT)"
  logs2 = [["", start + seconds + 3, "freqtrade.freqtradebot", "WARNING", low]]
  assert radar.view(state, trades, logs2, now)["pairs"]["E/USDT"][0][3:5] == [
    "blocked",
    "freqtrade: Available balance (5.1 USDT) is lower than stake amount (85.0 USDT)",
  ]
  sell = "Sell order cancelled due to timeout for Trade(id=9, pair=E/USDT, amount=10, is_short=False, leverage=3)."
  buy = "Buy order cancelled due to timeout for Trade(id=9, pair=E/USDT, amount=10, is_short=False, leverage=3)."
  state["config"]["max_open_trades"] = 9
  assert radar.view(state, trades, [["", start + 900, "f", "INFO", sell]], now)["pairs"]["E/USDT"][0][3] == "not taken"
  got = radar.view(state, trades, [["", start + 900, "f", "INFO", buy]], now)["pairs"]["E/USDT"][0][3:5]
  assert got == ["blocked", "entry order not filled (timeout)"]
  full = "Buy order fully cancelled for Trade(id=9, pair=E/USDT, amount=10, is_short=False, leverage=3)."
  got = radar.view(state, trades, [["", start + 900, "f", "INFO", full]], now)["pairs"]["E/USDT"][0][3:5]
  assert got == ["blocked", "entry order not filled (cancelled)"]
  assert view["pairs"]["D/USDT"][0][1] == "S" and view["pairs"]["G/USDT"][0][5] == 1 and view["summary"][GUARDS[0]] == 1
  assert (
    view["pairs_watched"] == 7 and "A/USDT" in view["pairs"] and len(view["pairs"]["A/USDT"]) == 1
  )  # quiet candle left out


def test_radar_saved(tmp_path):
  # signals, guard runs and reason lines survive a restart; a guard off for 3 candles in a row is one cell
  from nfiforge.radar import GUARDS, Radar
  from nfiforge.store import Store

  db, seconds, now = Store(tmp_path), 300, time.time() // 300 * 300
  cols = ["__date_ts", "enter_long", "enter_short", "enter_tag", *GUARDS]
  ok, off = [True] * len(GUARDS), [False] + [True] * (len(GUARDS) - 1)
  start = now - 3 * 86400
  data = [[start * 1000, 1, 0, "12", *ok]] + [[(start + step * seconds) * 1000, 0, 0, None, *off] for step in (1, 2, 3)]
  radar = Radar(db, "B")
  radar.add("A/USDT", {"columns": cols, "data": data})
  why = "[x] Cancelling entry for A/USDT due to insufficient free slots."
  radar.log(["", start + seconds + 10, "NFI", "INFO", why])
  radar.log(["", start, "NFI", "INFO", "nothing to keep"])
  radar.prune(["A/USDT"], now)
  reloaded = Radar(db, "B")
  assert reloaded.resume == pytest.approx(now) and len(reloaded.reasons) == 1
  state = {"config": {"timeframe": "5m"}, "locks": {"locks": []}}
  cells = reloaded.view(state, [], [], now)["pairs"]["A/USDT"]
  assert cells[0][3:5] == ["blocked", "strategy: insufficient free slots"]
  assert len(cells) == 2 and cells[1][5] == 1 and cells[1][6] == 3
  assert reloaded.view(state, [], [], now, since=now - 86400)["pairs"] == {}  # 3 days old: outside a 24 h window
  reloaded.prune(["A/USDT"], now + 8 * 86400)  # aged out of the 7 days: gone from memory and the db
  assert Radar(db, "B").rows == {} and db.radar_logs("B", 0) == []


async def test_radar_live(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.bots[0].radar = True
  config.data_dir = str(tmp_path)
  app = create_app(config)
  async with (
    app.router.lifespan_context(app),
    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
  ):
    await _signin(app, client, role="viewer")
    assert await _wait(lambda: app.state.bots["Fake"].radar.swept, timeout=8)
    view = (await client.get("/api/bots/Fake/radar")).json()
    assert view["enabled"] and view["timeframe"] == "5m" and view["pairs_watched"] >= 1
    pair = next(iter(view["pairs"]))
    cells = view["pairs"][pair]
    assert (
      any(cell[1] == "L" and cell[2] == "144" for cell in cells) and cells[-1][5] == 1
    )  # signal + guard off on the last
    assert view["summary"]["protections_long_global"] >= 1


async def test_trade_chart_picked_timeframe():
  from nfiforge.connectors.market import MAX_CANDLES, CandleSource

  asked = []

  class Ex:
    async def fetch_ohlcv(self, pair, timeframe, since, limit):
      asked.append((timeframe, since))
      return [[since + i * 3600_000, 1, 1, 1, 1, 1] for i in range(min(limit, 3))]

  source = CandleSource()
  source._exchange = lambda exchange, futures: Ex()
  end = 1_700_000_000.0
  result = await source.candles("binance", True, "BTC/USDT:USDT", end - 2 * 86400, end, "1h")
  assert result["timeframe"] == "1h" and not result["clipped"] and asked[0][0] == "1h"
  # 72 days at 5m is more than MAX_CANDLES: the start moves up so the newest MAX_CANDLES candles are fetched
  asked.clear()
  result = await source.candles("binance", True, "BTC/USDT:USDT", end - 72 * 86400, end, "5m")
  assert result["timeframe"] == "5m" and result["clipped"] and asked[0][0] == "5m"
  assert asked[0][1] == int((min(end + 18 * 86400, __import__("time").time()) - MAX_CANDLES * 300) * 1000)
  assert (await source.candles("binance", True, "BTC/USDT:USDT", end - 3600, end))["timeframe"] == "5m"


async def test_trade_chart_bad_timeframe(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  transport = httpx.ASGITransport(app=app)
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://t") as client:
    await _signin(app, client)
    assert await _wait(lambda: app.state.bots["Fake"].state["config"], timeout=8)
    response = await client.get(
      "/api/bots/Fake/candles", params={"pair": "BTC/USDT", "start": 1, "end": 2, "timeframe": "7m"}
    )
    assert response.status_code == 400
