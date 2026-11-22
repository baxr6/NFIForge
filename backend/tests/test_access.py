import httpx
import pytest
from fake_freqtrade import PASSWORD, USER
from nfiforge.access import Access, clean
from nfiforge.config import AppConfig
from test_phase0 import TEST_PW, _signin, _wait


def _cfg(url: str, tmp_path) -> AppConfig:
  bot = {"url": url, "username": USER, "password": PASSWORD}
  config = AppConfig.model_validate(
    {"bots": [{"name": "Fake", **bot}, {"name": "Other", **bot}], "update_check": False, "poll": {"status": 0.2}}
  )
  config.data_dir = str(tmp_path)
  return config


def test_clean_and_rules():
  assert clean(None) is None and clean({"bots": None, "pages": None}) is None  # everything = nothing stored
  for bad in ("x", {"bots": "Fake"}, {"bots": [""]}, {"pages": ["trading"]}, {"pages": "logs"}):
    with pytest.raises(ValueError):
      clean(bad)
  viewer = Access({"role": "viewer", "access": clean({"bots": ["Fake", "Fake"], "pages": ["logs"]})})
  assert viewer.bots == ["Fake"] and viewer.pages == ["logs"] and not viewer.percent
  assert viewer.refuse("/api/bots/Fake/state", {}) is None and viewer.refuse("/api/bots/Fake/logs", {}) is None
  assert viewer.refuse("/api/bots/Other/state", {}) and viewer.refuse("/api/bots/Fake/radar", {})
  assert (
    viewer.refuse("/api/host", {})
    and viewer.refuse("/api/server/history", {})
    and viewer.refuse("/api/notifications", {})
  )
  assert viewer.refuse("/api/btcgate/snapshot", {}) and viewer.refuse("/api/orderflow/bars", {"bot": "Fake"})
  assert viewer.refuse("/api/settings", {}) is None and viewer.refuse("/api/bots", {}) is None
  flow_viewer = Access({"role": "viewer", "access": clean({"bots": ["Fake"], "pages": ["orderflow"]})})
  assert flow_viewer.refuse("/api/orderflow/bars", {"bot": "Fake"}) is None
  assert flow_viewer.refuse("/api/orderflow/bars", {"bot": "Other"})
  # live messages
  assert viewer.message({"type": "state_diff", "bot": "Fake"}) and not viewer.message({"type": "event", "bot": "Other"})
  assert not viewer.message({"type": "host"}) and not viewer.message({"type": "notifications_read"})
  assert viewer.message({"type": "settings"})
  notes_viewer = Access({"role": "viewer", "access": clean({"bots": ["Fake"], "pages": ["notifications"]})})
  assert (
    notes_viewer.note({"bot": "Fake"})
    and not notes_viewer.note({"bot": "Other"})
    and not notes_viewer.note({"bot": None})
  )  # host alert: server
  # percent only: the percent view and signing in, nothing else
  percent_viewer = Access({"role": "viewer", "access": clean({"percent": True})})
  assert (
    percent_viewer.percent
    and percent_viewer.refuse("/api/bots/Fake/state", {})
    and percent_viewer.refuse("/api/settings", {})
  )
  assert percent_viewer.refuse("/api/auth/status", {}) is None and percent_viewer.refuse("/api/view", {}) is None
  # admins: everything, whatever is stored
  admin = Access({"role": "admin", "access": clean({"bots": [], "percent": True})})
  assert admin.refuse("/api/bots/Other/logs", {}) is None and admin.message({"type": "host"}) and admin.page("server")


async def test_viewer_access(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  app = create_app(_cfg(url, tmp_path))
  db = app.state.db
  transport = httpx.ASGITransport(app=app)
  async with (
    app.router.lifespan_context(app),
    httpx.AsyncClient(transport=transport, base_url="http://t") as admin,
    httpx.AsyncClient(transport=transport, base_url="http://t") as viewer,
  ):
    await _signin(app, admin)
    await _signin(app, viewer, role="viewer")
    assert await _wait(lambda: app.state.bots["Other"].state["connected"])
    me = (await viewer.get("/api/auth/status")).json()["user"]
    assert me["access"] == {"bots": None, "pages": None, "percent": False}  # as before: everything
    assert len((await viewer.get("/api/bots")).json()) == 2

    # the admin limits the viewer to one bot and its logs; the viewer's next request follows it
    user_id = me["id"]
    response = await admin.put(f"/api/users/{user_id}", json={"access": {"bots": ["Fake"], "pages": ["logs"]}})
    assert response.status_code == 200 and response.json()["access"]["bots"] == ["Fake"]
    assert (await admin.put(f"/api/users/{user_id}", json={"access": {"pages": ["nope"]}})).status_code == 422
    assert [bot["name"] for bot in (await viewer.get("/api/bots")).json()] == ["Fake"]
    assert (await viewer.get("/api/bots/Fake/state")).status_code == 200
    assert (await viewer.get("/api/bots/Other/state")).status_code == 403
    assert (await viewer.get("/api/bots/Other%20x/state")).status_code == 403
    assert (await viewer.get("/api/bots/Fake/logs")).status_code == 200
    assert (await viewer.get("/api/bots/Fake/radar")).status_code == 403
    assert (await viewer.get("/api/host")).status_code == 403
    assert (await viewer.get("/api/notifications")).status_code == 403
    assert (await viewer.get("/api/update")).status_code == 403  # update notice: admins only
    # the admin still sees both
    assert len((await admin.get("/api/bots")).json()) == 2

    # notifications: only the viewer's bot's, and the server's only with the Server page
    db.add_note("Fake", "alert", "warn", "a", "fake alert", "")
    db.add_note("Other", "alert", "warn", "b", "other alert", "")
    db.add_note(None, "alert", "warn", "c", "disk full", "")
    await admin.put(f"/api/users/{user_id}", json={"access": {"bots": ["Fake"], "pages": ["notifications"]}})
    got = (await viewer.get("/api/notifications")).json()
    assert [n["title"] for n in got["items"]] == ["fake alert"] and got["unread"] == 1
    await admin.put(f"/api/users/{user_id}", json={"access": {"bots": ["Fake"], "pages": ["notifications", "server"]}})
    got = (await viewer.get("/api/notifications")).json()
    assert {n["title"] for n in got["items"]} == {"fake alert", "disk full"}
    assert len((await admin.get("/api/notifications")).json()["items"]) == 3

    # percent only: nothing but signing in (and, later, the percent view)
    await admin.put(f"/api/users/{user_id}", json={"access": {"percent": True}})
    assert (await viewer.get("/api/bots")).status_code == 403
    assert (await viewer.get("/api/settings")).status_code == 403
    assert (await viewer.get("/api/auth/status")).json()["user"]["access"]["percent"] is True

    # back to everything: stored as empty
    await admin.put(f"/api/users/{user_id}", json={"access": None})
    assert db.user_by_id(user_id)["access"] is None
    assert len((await viewer.get("/api/bots")).json()) == 2


async def test_push_follows_access(tmp_path):
  from nfiforge.auth import hash_password
  from nfiforge.store import Store

  db = Store(tmp_path / "x.db")
  boss = db.add_user("boss", hash_password(TEST_PW), "admin")
  viewer_id = db.add_user("vw", hash_password(TEST_PW), "viewer")
  db.update_user(viewer_id, access=clean({"bots": ["Fake"], "pages": ["notifications"]}))
  for user_id in (boss, viewer_id):
    db.add_push(user_id, f"https://fcm.googleapis.com/{user_id}", "k", "a", "")
  subs = db.push_subs()
  assert {subscription["endpoint"]: Access(subscription).note({"bot": "Other"}) for subscription in subs} == {
    f"https://fcm.googleapis.com/{boss}": True,
    f"https://fcm.googleapis.com/{viewer_id}": False,
  }
