import sqlite3
import time

import httpx
from nfiforge.config import PollIntervals
from nfiforge.connectors.freqtrade import BotConnector, fresh_db
from nfiforge.store import Store
from test_phase0 import _cfg, _signin, _wait


def test_fresh_db_rules():
  closed = {5: 500, 6: 600, 7: 700}
  assert not fresh_db(None, closed)  # nothing remembered yet
  assert not fresh_db((5, 500), closed)  # same oldest trade
  assert not fresh_db((4, 400), closed)  # oldest trade deleted on the bot
  assert fresh_db((5, 500), {5: 999})  # same id, another trade: counting from 1 again
  assert fresh_db((5, 500), {1: 900, 2: 950})  # ids below the old oldest
  assert fresh_db((5, 500), {})  # every closed trade gone


def test_excursions_rekeyed_on_upgrade(tmp_path, monkeypatch):
  # an install from before: excursions keyed (bot, trade_id) only
  old = Store.MIGRATIONS[:13]
  monkeypatch.setattr(Store, "MIGRATIONS", old)
  Store(tmp_path)
  connection = sqlite3.connect(tmp_path / "nfiforge.db")
  connection.execute("INSERT INTO excursions VALUES ('B', 1, 5.0, -2.0, '1m', NULL, 0)")
  connection.commit()
  connection.close()
  monkeypatch.undo()
  store = Store(tmp_path)
  assert store.excursions("B") == {}  # measured again, now with the open time
  store.add_excursion("B", 1, 1000, 5.0, -2.0, "1m", None)
  store.add_excursion("B", 1, 2000, 1.0, -1.0, "1m", None)  # a new database's #1: its own row
  assert store.excursions("B") == {(1, 1000): (5.0, -2.0), (1, 2000): (1.0, -1.0)}


async def test_connector_spots_fresh_db(fake, tmp_path):
  fake_bot, url, _ = fake
  store = Store(tmp_path)
  connector = BotConnector(_cfg(url).bots[0], PollIntervals(), lambda message: None, store)
  try:
    trades = fake_bot.state.data["/trades"]["trades"]
    base = trades[0]
    trades[:] = [{**base, "trade_id": i, "open_timestamp": i * 1000, "is_open": False} for i in (3, 4, 5)]
    await connector.sync_history(full=True)
    assert store.db_sig("Fake") == (3, 3000) and not connector.state["fresh_db"]
    trades[:] = trades[1:]  # oldest deleted on the bot: not new, the next oldest is remembered
    await connector.sync_history(full=True)
    assert store.db_sig("Fake") == (4, 4000) and not connector.state["fresh_db"]
    trades[:] = [{**base, "trade_id": 1, "open_timestamp": 9000, "is_open": False}]  # new database
    await connector.sync_history(full=True)
    assert connector.state["fresh_db"] and store.db_sig("Fake") == (4, 4000)  # kept until reset
  finally:
    await connector.client.close()


async def test_reset_route(fake, tmp_path):
  fake_bot, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  async with (
    app.router.lifespan_context(app),
    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
  ):
    db, bot = app.state.db, app.state.bots["Fake"]
    assert await _wait(lambda: bot.history, timeout=8)
    for i in range(3):
      db.add_equity("Fake", 100, 0, timestamp=time.time() - i)
    db.add_equity("Other", 100, 0)
    db.add_note("Fake", "trade", "info", "k", "t")
    db.add_excursion("Fake", 1, 1, 1.0, -1.0, "1m", None)
    db.set_db_sig("Fake", (99, 1))
    bot.logs_kept.append(["", 0, "x", "INFO", "old line"])

    await _signin(app, client, role="viewer")
    assert (await client.post("/api/manage/bots/Fake/reset", json={"parts": ["equity"]})).status_code == 403
    await _signin(app, client)
    data = (await client.get("/api/manage/bots/Fake/data")).json()
    assert data["counts"]["equity"] == 3 and data["counts"]["notes"] >= 1 and data["counts"]["logs"] >= 1

    # nothing ticked: keeps everything, remembers the database as it is now
    result = (await client.post("/api/manage/bots/Fake/reset", json={"parts": []})).json()
    assert result["cleared"] == {} and db.bot_data("Fake")["equity"] == 3 and db.db_sig("Fake") != (99, 1)

    result = (
      await client.post("/api/manage/bots/Fake/reset", json={"parts": ["equity", "notes", "excursions", "logs"]})
    ).json()
    assert result["cleared"]["equity"] == 3 and result["cleared"]["excursions"] == 1
    left = db.bot_data("Fake")
    assert left["equity"] == left["notes"] == left["excursions"] == 0 and not bot.logs_kept
    assert db.bot_data("Other")["equity"] == 1  # other bots untouched
    assert not bot.state["fresh_db"]
