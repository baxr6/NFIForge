import asyncio

import httpx
import pytest
from nfiforge import share
from nfiforge.access import clean as clean_access
from test_access import _cfg
from test_phase0 import _signin, _wait

# key parts that would carry an amount; none may appear anywhere in a share answer
BANNED = ("stake", "amount", "balance", "wallet", "abs", "price", "rate", "cost", "capital", "fiat", "fee", "funding")


def _keys(node, path=""):
  if isinstance(node, dict):
    for key, value in node.items():
      yield f"{path}.{key}", key
      yield from _keys(value, f"{path}.{key}")
  elif isinstance(node, list):
    for value in node:
      yield from _keys(value, path)


def _numbers(node):
  if isinstance(node, dict):
    for value in node.values():
      yield from _numbers(value)
  elif isinstance(node, list):
    for value in node:
      yield from _numbers(value)
  elif isinstance(node, int | float) and not isinstance(node, bool):
    yield node


def _amounts(state, history):
  # every amount-like number the bot gave us
  out = set()
  for trade in [*(state.get("status") or []), *history]:
    for key, value in trade.items():
      if any(banned in key for banned in BANNED) and isinstance(value, int | float) and not isinstance(value, bool):
        out.add(float(value))
  for value in (state.get("balance") or {}).values():
    if isinstance(value, int | float):
      out.add(float(value))
  return {value for value in out if abs(value) > 1}  # 0 / 1 turn up as counts and leverage


def _no_amounts(answer, state, history):
  for path, key in _keys(answer):
    assert not any(banned in key.lower() for banned in BANNED), f"amount-like key {path}"
  leaked = _amounts(state, history) & {float(number) for number in _numbers(answer)}
  assert not leaked, f"amounts in the answer: {leaked}"


def test_bot_view_math():
  day = 86400 * 1000
  now = 1_700_000_000.0
  today = (now - now % 86400) * 1000
  state = {
    "balance": {"starting_capital": 1000, "total": 1150},
    "config": {"max_open_trades": 4, "exchange": "bybit"},
    "status": [{"pair": "A/USDT", "profit_abs": 23, "total_profit_ratio": 0.05, "stake_amount": 400, "leverage": 3}],
  }
  history = [
    {
      "open_timestamp": today - 40 * day,
      "close_timestamp": today - 39 * day,
      "close_profit_abs": 120,
      "close_profit": 0.12,
    },
    {
      "open_timestamp": today - 3 * day,
      "close_timestamp": today - 2 * day,
      "close_profit_abs": -110,
      "close_profit": -0.1,
    },
    {"open_timestamp": today, "close_timestamp": today + 1000, "close_profit_abs": 160, "close_profit": 0.16},
  ]
  view = share.bot_view(state, history, "Bot 1", dict.fromkeys(share.OPTS, True), now=now)
  summary = view["summary"]
  assert summary["all"] == 17.0 and summary["today"] == pytest.approx(160 / 1010 * 100, abs=1e-3)
  assert summary["week"] == pytest.approx(50 / 1120 * 100, abs=1e-3) and summary["month"] == summary["week"]
  assert summary["won"] == pytest.approx(66.667, abs=1e-3) and summary["profit_factor"] == pytest.approx(
    280 / 110, abs=0.01
  )
  assert summary["drawdown"] == pytest.approx(-110 / 1120 * 100, abs=1e-3)
  assert (
    summary["open"] == pytest.approx(23 / 1170 * 100, abs=1e-3) and summary["slots"] == 1 and summary["slots_max"] == 4
  )
  assert [point[1] for point in view["equity"]] == [100.0, 112.0, 101.0, 117.0]
  assert [daily_row["pct"] for daily_row in view["daily"]] == [
    12.0,
    pytest.approx(-110 / 1120 * 100, abs=1e-3),
    pytest.approx(160 / 1010 * 100, abs=1e-3),
  ]
  assert view["open"][0]["pct"] == 5.0 and view["closed"][0]["pct"] == 16.0
  _no_amounts(view, state, history)
  # switches off: no lists, no tags, no exchange
  off = share.bot_view(state, history, "Bot 1", dict.fromkeys(share.OPTS, False), now=now)
  assert "open" not in off and "closed" not in off and off["exchange"] is None
  # no starting capital: no account percentages rather than wrong ones
  bare = share.bot_view({"status": []}, history, "x", dict.fromkeys(share.OPTS, False), now=now)
  assert bare["summary"]["all"] is None and bare["equity"] == [] and bare["daily"] == []


def test_clean():
  ok = share.clean({"name": "friends", "bots": ["A"], "days": 30, "positions": 1}, ["A", "B"])
  assert ok == {
    "name": "friends",
    "bots": ["A"],
    "days": 30,
    "opts": {"positions": True, "trades": False, "tags": False, "names": False},
  }
  for bad in (
    {"name": "", "bots": ["A"]},
    {"name": "x", "bots": []},
    {"name": "x", "bots": ["C"]},
    {"name": "x", "bots": ["A"], "days": 0},
  ):
    with pytest.raises(ValueError):
      share.clean(bad, ["A", "B"])


async def test_share_links(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  app = create_app(_cfg(url, tmp_path))
  transport = httpx.ASGITransport(app=app)
  async with (
    app.router.lifespan_context(app),
    httpx.AsyncClient(transport=transport, base_url="http://t") as admin,
    httpx.AsyncClient(transport=transport, base_url="http://t") as anon,
  ):
    await _signin(app, admin)
    fake_bot = app.state.bots["Fake"]
    assert await _wait(lambda: fake_bot.state["connected"] and fake_bot.history and fake_bot.state["status"])

    # making one: admins only, checked
    body = {"name": "friends", "bots": ["Fake"], "days": 7, "positions": True, "trades": True, "tags": True}
    assert (await anon.post("/api/manage/shares", json=body)).status_code == 401
    assert (await admin.post("/api/manage/shares", json={**body, "bots": ["Nope"]})).status_code == 422
    made = (await admin.post("/api/manage/shares", json=body)).json()
    code = made["code"]
    assert made["path"] == f"/s/{code}" and len(code) >= 40
    listed = (await admin.get("/api/manage/shares")).json()
    assert listed[0]["name"] == "friends" and "code" not in listed[0] and listed[0]["expires"]

    # opening it: no account needed, only the shared bot, no amounts anywhere, not cached
    response = await anon.get(f"/api/share/{code}")
    assert (
      response.status_code == 200
      and response.headers["cache-control"] == "no-store"
      and "noindex" in response.headers["x-robots-tag"]
    )
    page = response.json()
    assert page["title"] == "friends" and [bot["name"] for bot in page["bots"]] == ["Bot 1"]  # names off
    assert page["bots"][0]["open"] and page["bots"][0]["closed"]
    _no_amounts(page, fake_bot.state, list(fake_bot.history.values()))
    assert (await admin.get("/api/manage/shares")).json()[0]["opens"] == 1
    # nothing else opens without an account
    for path in ("/api/bots", "/api/bots/Fake/state", "/api/view", "/api/settings"):
      assert (await anon.get(path)).status_code == 401

    # wrong and revoked codes look the same
    assert (await anon.get("/api/share/" + "x" * 43)).status_code == 404
    assert (await admin.delete(f"/api/manage/shares/{made['id']}")).status_code == 200
    assert (await anon.get(f"/api/share/{code}")).status_code == 404
    # expired
    app.state.db._query("UPDATE shares SET expires = 1", write=True)

    # percent-only viewer: /api/view for their bots, nothing else
    viewer = httpx.AsyncClient(transport=transport, base_url="http://t")
    async with viewer:
      await _signin(app, viewer, role="viewer", name="pv")
      user_id = app.state.db.user_by_name("pv")["id"]
      app.state.db.update_user(user_id, access=clean_access({"bots": ["Other"], "percent": True}))
      view = (await viewer.get("/api/view")).json()
      assert [bot["name"] for bot in view["bots"]] == ["Other"]
      assert (await viewer.get("/api/bots/Other/state")).status_code == 403
      _no_amounts(view, app.state.bots["Other"].state, list(app.state.bots["Other"].history.values()))


async def test_share_rate_limit(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  app = create_app(_cfg(url, tmp_path))
  async with (
    app.router.lifespan_context(app),
    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
  ):
    got = await asyncio.gather(*(client.get("/api/share/" + "y" * 43) for _ in range(65)))
    assert sorted({response.status_code for response in got}) == [404, 429]
