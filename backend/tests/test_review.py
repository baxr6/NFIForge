import httpx
import pytest
from nfiforge.config import BotConfig
from nfiforge.health import checks
from nfiforge.store import Store
from test_phase0 import _cfg, _signin


def test_read_marker_stays_in_range(tmp_path):
  # a huge id once broke the notifications list for everyone
  db = Store(tmp_path)
  note = db.add_note("b", "alert", "bad", "k", "t")
  db.set_read(10**30)
  assert db.read_marker() == note["id"] and db.unread() == 0
  db.add_note("b", "alert", "bad", "k", "t2")
  assert db.unread() == 1
  db.set_read(-5)
  assert db.read_marker() == 0


@pytest.mark.parametrize("name", ["a/b", "", "  ", "x" * 41, "a%2Fb", "a?b", "tab\there"])
def test_bad_bot_names(name):
  with pytest.raises(ValueError):
    BotConfig(name=name, url="http://x", username="u", password="p")


def test_good_bot_names():
  assert BotConfig(name=" Bybit Live ", url="http://x", username="u", password="p").name == "Bybit Live"


@pytest.mark.parametrize("container", ["bad name", "-x", "a/b", "x" * 129])
def test_bad_container_names(container):
  with pytest.raises(ValueError):
    BotConfig(name="b", url="http://x", username="u", password="p", container=container)


def test_good_container_names():
  bot = BotConfig(name="b", url="http://x", username="u", password="p", container=" freqtrade_container86 ")
  assert bot.container == "freqtrade_container86"
  assert BotConfig(name="b", url="http://x", username="u", password="p", container=" ").container is None


def test_unlimited_slots_health():
  state = {"connected": True, "config": {"stake_amount": 100, "stake_currency": "USDT", "max_open_trades": -1}}
  assert any(check["title"] == "Stake 100 USDT × unlimited slots" for check in checks(state, False, False, None))


async def test_review_routes(fake, tmp_path):
  fake_bot, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  config.write_actions = True
  config.bots[0].trading = True
  app = create_app(config)
  local = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=local, base_url="http://t") as client:
    await _signin(app, client)
    # read marker: junk is refused
    assert (await client.post("/api/notifications/read", json={"id": "x"})).status_code == 422
    assert (await client.post("/api/notifications/read", json={"id": 10**30})).status_code == 200
    assert (await client.get("/api/notifications")).status_code == 200
    # no infinity sent to a bot
    response = await client.post(
      "/api/trade/Fake/enter", json={"pair": "BTC/USDT:USDT", "side": "long", "price": "inf"}
    )
    assert response.status_code == 422
    # a bot whose dry_run can't be read counts as live
    del fake_bot.state.data["/show_config"]["dry_run"]
    response = await client.post("/api/trade/Fake/lock", json={"pair": "*", "minutes": 5})
    assert response.status_code == 428
    # an unreachable bot on a trade lookup: says so, not a bare 500
    bot = app.state.bots["Fake"]

    async def down(*args, **kwargs):
      raise httpx.ConnectError("refused")

    real, bot.client.get = bot.client.get, down
    response = await client.post("/api/trade/Fake/exit", json={"tradeid": 1})
    bot.client.get = real
    assert response.status_code == 502 and "can't reach Fake" in response.json()["detail"]
    # bad bot details: the real reason, not pydantic's help link
    body = {"name": "a/b", "url": url, "username": "u", "password": "p"}
    response = await client.post("/api/manage/bots", json=body)
    assert response.status_code == 422 and "1-40 characters" in response.json()["detail"]
    response = await client.post("/api/manage/bots", json={**body, "name": "ok", "url": "ftp://x"})
    assert response.status_code == 422 and "http://" in response.json()["detail"]
    # through a proxy on this machine (tailscale serve) isn't "this machine"
    response = await client.post("/api/manage/bots/test", json=body, headers={"X-Forwarded-For": "100.64.0.9"})
    assert response.status_code == 403 and "this machine" in response.json()["detail"]


def _connector(url):
  from nfiforge.config import PollIntervals
  from nfiforge.connectors.freqtrade import BotConnector

  return BotConnector(_cfg(url).bots[0], PollIntervals(), lambda message: None)


async def test_one_failed_request_isnt_down(fake):
  import time

  _, url, _ = fake
  connector = _connector(url)
  try:
    connector._fail("first contact failed")
    assert not connector.state["connected"]
    await connector._bootstrap()
    connector._fail("Fake: /locks -> HTTP 500")  # the bot answered just now: still connected, error noted
    assert connector.state["connected"] and "locks" in connector.state["error"]
    connector._last_ok = time.time() - 20  # nothing has answered for 20 s: down
    connector._fail("Fake: cannot reach")
    assert not connector.state["connected"]
  finally:
    await connector.client.close()


async def test_history_drops_deleted_and_keeps_today(fake):
  import time

  fake_bot, url, _ = fake
  connector = _connector(url)
  try:
    trades = fake_bot.state.data["/trades"]["trades"]
    base = trades[0]
    now = time.time() * 1000
    # 250 closes in the last hours: all of them reach the page, not just the newest 200
    trades[:] = [{**base, "trade_id": i, "close_timestamp": now - i * 60000} for i in range(1, 251)]
    await connector.sync_history(full=True)
    assert len(connector.history) == 250 and len(connector.state["trades"]["trades"]) == 250
    # a trade deleted on the bot goes at the next full read
    trades[:] = trades[1:]
    await connector.sync_history(full=False)
    assert 1 in connector.history
    await connector.sync_history(full=True)
    assert 1 not in connector.history and len(connector.history) == 249
  finally:
    await connector.client.close()


def test_snapshot_carries_kept_events(fake, tmp_path):
  from fastapi.testclient import TestClient
  from nfiforge.app import create_app
  from nfiforge.auth import hash_password
  from test_phase0 import TEST_PW

  _, url, _ = fake
  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  with TestClient(app) as client:
    app.state.db.add_user("w", hash_password(TEST_PW), "viewer")
    assert client.post("/api/auth/login", json={"username": "w", "password": TEST_PW}).status_code == 200
    app.state.bots["Fake"].events.append({"ts": 1.0, "type": "exit_fill", "data": {"pair": "BTC/USDT:USDT"}})
    with client.websocket_connect("/ws") as websocket:
      snapshot = websocket.receive_json()
    assert snapshot["type"] == "snapshot" and snapshot["events"]["Fake"][-1]["type"] == "exit_fill"


def test_closed_trade_wakes_history(fake):
  # an open trade leaving /status reads the closes now, not at the next minute
  _, url, _ = fake
  connector = _connector(url)
  connector._set("status", [{"trade_id": 1}, {"trade_id": 2}])
  connector._set("status", [{"trade_id": 1}, {"trade_id": 2}, {"trade_id": 3}])
  assert not connector._history_wake.is_set()
  connector._set("status", [{"trade_id": 1}, {"trade_id": 3}])
  assert connector._history_wake.is_set()
