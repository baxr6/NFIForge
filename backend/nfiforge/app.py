# browser api + one websocket that pushes live bot state and events

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from nfiforge import __version__, share
from nfiforge.access import Access
from nfiforge.access import clean as clean_access
from nfiforge.alerts import Notifier
from nfiforge.auth import (
  COOKIE,
  ROLES,
  SESSION_DAYS,
  RateLimit,
  check_login,
  digest,
  hash_password,
  new_secret,
  password_problem,
  username_problem,
)
from nfiforge.config import AppConfig, BotConfig, OrderflowConfig
from nfiforge.connectors.freqtrade import AuthError, BotConnector, FreqtradeClient
from nfiforge.connectors.host import HostMonitor
from nfiforge.connectors.market import TF_SEC, CandleSource
from nfiforge.excursions import Excursions
from nfiforge.fx import Fx
from nfiforge.health import checks
from nfiforge.hub import Hub
from nfiforge.push import Push, allowed
from nfiforge.radar import Radar
from nfiforge.settings import Settings, SettingsStore
from nfiforge.store import Store
from nfiforge.uibots import UiBots
from nfiforge.updates import check as check_update
from nfiforge.updates import latest_release

log = logging.getLogger(__name__)


def create_app(config: AppConfig) -> FastAPI:
  def _orderflow(changes: dict) -> OrderflowConfig:
    # config.yaml's order flow options with the settings page's changes over them (it can't switch it on / off)
    return OrderflowConfig.model_validate(
      config.orderflow.model_dump() | {key: value for key, value in changes.items() if key != "enabled"}
    )

  hub = Hub()
  store = SettingsStore(config.data_dir)
  db = Store(config.data_dir)
  # in docker only the host's /proc, cgroup files and one disk probe are mounted (never the whole disk)
  host = HostMonitor(
    hub.publish,
    disk_path=os.environ.get("NFIFORGE_HOST_DISK", "/"),
    host_root=os.environ.get("NFIFORGE_HOST_ROOT", "/"),
  )
  market = CandleSource()
  fx_rates = Fx()
  push = Push(config.data_dir, db)
  notifier = Notifier(db, lambda: store.settings.alerts, hub.publish, push.notify)
  ui_bots = UiBots(config.data_dir)
  from_config = {bot_config.name for bot_config in config.bots}
  # config.yaml bots first; ui-added ones can't take a config bot's name
  added = [bot_config for bot_config in ui_bots.load() if bot_config.name not in from_config]

  def _connector(bot_config: BotConfig) -> BotConnector:
    connector = BotConnector(bot_config, config.poll, hub.publish, db, notifier.trade_event, market)
    connector.state["trading"] = (
      config.write_actions and bot_config.trading
    )  # the browser shows trade buttons only when true
    connector.state["radar"] = bot_config.radar
    connector.state["container"] = bot_config.container
    return connector

  bots: dict[str, BotConnector] = {
    bot_config.name: _connector(bot_config) for bot_config in [*config.bots, *added] if bot_config.enabled
  }
  gate = None
  if config.btcgate.enabled:  # off = not imported, no worker, no routes
    from nfiforge.btcgate.settings import ALERT_TYPES
    from nfiforge.btcgate.supervisor import Supervisor

    wording = {name: (label, meaning) for name, label, meaning in ALERT_TYPES}

    def _signal(row: dict) -> None:
      if row.get("signal") in wording:
        notifier.btcgate_signal(row, *wording[row["signal"]])

    book_keys = ("pair", "amount", "open_rate", "current_rate", "is_short", "stake_amount", "leverage")

    def _bot_coins() -> dict:  # every connected bot's whitelist and open trades: the worker's coin list and books
      whitelist, blacklist, open_, books = set(), set(), set(), {}
      for name, connector in bots.items():
        whitelist |= set((connector.state["whitelist"] or {}).get("whitelist") or [])
        blacklist |= set((connector.state["blacklist"] or {}).get("blacklist") or [])
        trades = [trade for trade in connector.state["status"] or [] if trade.get("pair")]
        open_ |= {trade["pair"] for trade in trades}
        if connector.state.get("connected"):
          books[name] = [{key: trade.get(key) for key in book_keys} for trade in trades]
      return {"whitelist": sorted(whitelist), "blacklist": sorted(blacklist), "open": sorted(open_), "books": books}

    gate = Supervisor(Path(config.data_dir) / "btcgate", config.btcgate.memory_mb, _signal, _bot_coins)
  flow = None
  if config.orderflow.enabled:  # off = no worker, no routes
    from nfiforge.orderflow.routes import Orderflow

    def _open_pairs() -> list[dict]:  # every connected bot's open-trade pairs, on that bot's exchange
      out = []
      for connector in bots.values():
        bot_config = connector.state["config"] or {}
        if bot_config.get("exchange"):
          market = "swap" if bot_config.get("trading_mode") == "futures" else "spot"
          for trade in connector.state["status"] or []:
            if trade.get("pair"):
              out.append({"exchange": bot_config["exchange"], "market": market, "symbol": trade["pair"]})
      return out

    try:
      orderflow_settings = _orderflow(store.settings.orderflow)
    except ValidationError:  # a saved change no longer valid: config.yaml's options
      log.warning("order flow settings from the settings page are not valid any more: using config.yaml's")
      orderflow_settings = config.orderflow
    flow = Orderflow(
      Path(config.data_dir) / "orderflow",
      orderflow_settings.memory_mb,
      orderflow_settings.model_dump(exclude={"enabled", "memory_mb"}),
      _open_pairs,
      config.orderflow.model_dump(exclude={"enabled"}),
    )
  excursions = Excursions(db, market, bots)

  # host, containers and bot loop times once a minute, for the Server page's history
  async def _record_server() -> None:
    while True:
      await asyncio.sleep(60)
      if host.state:
        loops = {
          name: connector.state["loop_s"]
          for name, connector in bots.items()
          if connector.state.get("loop_s") is not None
        }
        await asyncio.to_thread(db.add_server, host.state, loops)

  @asynccontextmanager
  async def lifespan(app: FastAPI):
    await host.start()
    for connector in bots.values():
      await connector.start()
    alerts = asyncio.create_task(notifier.run(bots, lambda: host.state), name="alerts")
    record = asyncio.create_task(_record_server(), name="server-history")
    measure = asyncio.create_task(excursions.run(), name="excursions")
    if gate:
      await gate.start()
    if flow:
      await flow.start()
    yield
    if gate:
      await gate.stop()
    if flow:
      await flow.stop()
    for task in (alerts, record, measure):
      task.cancel()
    await asyncio.gather(alerts, record, measure, return_exceptions=True)
    await asyncio.gather(host.stop(), market.close(), *(connector.stop() for connector in bots.values()))

  app = FastAPI(title="NFIForge", version=__version__, lifespan=lifespan)
  app.state.bots, app.state.hub, app.state.settings, app.state.db = bots, hub, store, db
  app.state.notifier = notifier

  # ===========================================================================
  # ACCOUNTS: every api call needs a signed-in user (session cookie, HttpOnly, only its hash is stored).
  # admins change things (settings, layouts, bots, users); viewers look. no accounts yet -> nothing opens until
  # one is made with `./install.sh --add-user` (no web setup screen anyone on the network could reach first)
  # ===========================================================================
  limiter = RateLimit()
  PUBLIC = ("/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/pair")
  SHARED = "/api/share/"  # share links: no account, percent-only answer (share.py)
  ADMIN_PREFIXES = ("/api/manage/", "/api/users", "/api/trade/", "/api/update")

  def _session_user(session_id: str | None) -> dict | None:
    return db.session_user(digest(session_id)) if session_id else None

  @app.middleware("http")
  async def _auth(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC and not path.startswith(SHARED):
      user = await asyncio.to_thread(_session_user, request.cookies.get(COOKIE))
      if not user:
        return JSONResponse({"detail": "sign in first"}, status_code=401)
      admin_only = path.startswith(ADMIN_PREFIXES) or (path == "/api/settings" and request.method != "GET")
      admin_only |= path.startswith("/api/btcgate/") and request.method != "GET"  # btcgate settings and keys
      if admin_only and user["role"] != "admin":
        return JSONResponse({"detail": "only an admin can do that"}, status_code=403)
      access = Access(user)
      if why := access.refuse(path, dict(request.query_params)):
        return JSONResponse({"detail": why}, status_code=403)
      request.state.user, request.state.access = user, access
    # json-only writes: an html form on another site can't send these (with the samesite cookie, no csrf)
    writes = request.method in ("POST", "PUT", "PATCH") and path.startswith("/api/")
    if writes and "application/json" not in request.headers.get("content-type", ""):
      return JSONResponse({"detail": "send json"}, status_code=415)
    return await call_next(request)

  def _start_session(request: Request, response: Response, user: dict) -> None:
    session_id, sid_hash = new_secret()
    db.add_session(sid_hash, user["id"], SESSION_DAYS, request.headers.get("user-agent", ""))
    response.set_cookie(
      COOKIE,
      session_id,
      max_age=SESSION_DAYS * 86400,
      httponly=True,
      samesite="strict",
      secure=request.url.scheme == "https",
      path="/",
    )

  def _public_user(user: dict) -> dict:
    return {
      "id": user["id"],
      "username": user["username"],
      "role": user["role"],
      "disabled": bool(user["disabled"]),
      "access": Access(user).view(),
    }

  @app.get("/api/auth/status")
  async def auth_status(request: Request):
    user = _session_user(request.cookies.get(COOKIE))
    return {"has_users": bool(db.users()), "user": _public_user(user) if user else None}

  @app.post("/api/auth/login")
  async def auth_login(body: dict, request: Request, response: Response):
    who = request.client.host if request.client else "?"
    wait = limiter.blocked(who)
    if wait:
      raise HTTPException(429, f"too many failed sign-ins, try again in {wait / 60:.0f} min")
    user = db.user_by_name(str(body.get("username") or ""))
    if not check_login(user, str(body.get("password") or "")):
      limiter.fail(who)
      raise HTTPException(401, "wrong username or password")
    limiter.clear(who)
    _start_session(request, response, user)
    return _public_user(user)

  # ===========================================================================
  # PHONE ALERTS: a device subscribes (needs https, and on an iphone the app added to the home screen); every
  # alert is then pushed to it
  # ===========================================================================
  @app.get("/api/push/key")
  async def push_key():
    return {"key": push.public}

  @app.post("/api/push/subscribe")
  async def push_subscribe(request: Request, body: dict):
    endpoint, keys = body.get("endpoint"), body.get("keys") or {}
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not (isinstance(endpoint, str) and len(endpoint) <= 1024 and allowed(endpoint)):
      raise HTTPException(400, "not a browser push address")
    if not (isinstance(p256dh, str) and isinstance(auth, str) and len(p256dh) <= 128 and len(auth) <= 64):
      raise HTTPException(400, "missing push keys")
    db.add_push(request.state.user["id"], endpoint, p256dh, auth, request.headers.get("user-agent", "")[:200])
    return {"ok": True}

  @app.post("/api/push/unsubscribe")
  async def push_unsubscribe(request: Request, body: dict):
    if isinstance(body.get("endpoint"), str):
      db.drop_push(body["endpoint"], request.state.user["id"])
    return {"ok": True}

  @app.post("/api/push/test")
  async def push_test(request: Request):
    sent = await push.send(
      {"bot": None, "key": "test", "level": "info", "title": "NFIForge test alert", "detail": "phone alerts work"},
      request.state.user["id"],
    )
    return {"ok": sent > 0, "sent": sent}

  @app.post("/api/auth/logout")
  async def auth_logout(request: Request, response: Response, body: dict):
    if body.get("everywhere"):
      db.end_sessions(request.state.user["id"])
    else:
      db.end_session(digest(request.cookies.get(COOKIE, "")))
      # this device's phone alerts stop with it
      if isinstance(body.get("push"), str):
        db.drop_push(body["push"], request.state.user["id"])
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}

  @app.post("/api/auth/password")
  async def auth_password(body: dict, request: Request, response: Response):
    user = request.state.user
    if not check_login(user, str(body.get("current") or "")):
      raise HTTPException(403, "current password is wrong")
    new = str(body.get("new") or "")
    if problem := password_problem(new):
      raise HTTPException(422, problem)
    db.update_user(user["id"], pw=hash_password(new))
    db.end_sessions(user["id"])  # other devices sign in again
    _start_session(request, response, user)
    return {"ok": True}

  # phone pairing: install.sh --phone puts a one-time code for a user in the database; the phone swaps it for a
  # session. a code works once and for 10 minutes, so a shared link or screenshot of the qr code goes stale
  @app.post("/api/auth/pair")
  async def auth_pair(body: dict, request: Request, response: Response):
    who = request.client.host if request.client else "?"
    if limiter.blocked(who):
      raise HTTPException(429, "too many failed attempts, try again later")
    user_id = db.claim_pair(digest(str(body.get("code") or "")))
    user = db.user_by_id(user_id) if user_id else None
    if not user or user["disabled"]:
      limiter.fail(who)
      raise HTTPException(403, "this link was already used or has expired; make a new one with ./install.sh --phone")
    _start_session(request, response, user)
    return _public_user(user)

  # ---------------------------------------------------------------------------
  # USERS (admins only, enforced by the middleware)
  # ---------------------------------------------------------------------------
  @app.get("/api/users")
  async def users_list():
    return [{**_public_user(user), "sessions": db.session_count(user["id"])} for user in db.users()]

  @app.post("/api/users")
  async def users_add(body: dict):
    name, password, role = str(body.get("username") or "").strip(), str(body.get("password") or ""), body.get("role")
    if (
      problem := username_problem(name)
      or password_problem(password)
      or (None if role in ROLES else "role: admin or viewer")
    ):
      raise HTTPException(422, problem)
    if db.user_by_name(name):
      raise HTTPException(409, f"{name} already exists")
    return _public_user(db.user_by_id(db.add_user(name, hash_password(password), role)))

  def _other_user(user_id: int, request: Request) -> dict:
    user = db.user_by_id(user_id)
    if not user:
      raise HTTPException(404, "no such user")
    return user

  def _keeps_an_admin(
    user: dict, role: str | None = None, disabled: bool | None = None, removing: bool = False
  ) -> None:
    losing = user["role"] == "admin" and not user["disabled"] and (removing or role == "viewer" or disabled)
    if losing and db.admins() <= 1:
      raise HTTPException(409, "there must be at least one admin")

  @app.put("/api/users/{user_id}")
  async def users_update(user_id: int, body: dict, request: Request):
    user = _other_user(user_id, request)
    fields: dict = {}
    if "role" in body:
      if body["role"] not in ROLES:
        raise HTTPException(422, "role: admin or viewer")
      fields["role"] = body["role"]
    if "disabled" in body:
      fields["disabled"] = int(bool(body["disabled"]))
    if body.get("password"):
      if problem := password_problem(str(body["password"])):
        raise HTTPException(422, problem)
      fields["pw"] = hash_password(str(body["password"]))
    if "access" in body:  # viewers only; kept for an admin, used if they become a viewer
      try:
        fields["access"] = clean_access(body["access"])
      except ValueError as e:
        raise HTTPException(422, str(e)) from e
    _keeps_an_admin(user, fields.get("role"), bool(fields.get("disabled")))
    db.update_user(user_id, **fields)
    if "pw" in fields or fields.get("disabled") or fields.get("role") == "viewer":
      db.end_sessions(user_id)  # new password / blocked / fewer rights: sign in again
    return _public_user(db.user_by_id(user_id))

  @app.post("/api/users/{user_id}/logout")
  async def users_logout(user_id: int, request: Request):
    _other_user(user_id, request)
    db.end_sessions(user_id)
    return {"ok": True}

  @app.delete("/api/users/{user_id}")
  async def users_delete(user_id: int, request: Request):
    user = _other_user(user_id, request)
    _keeps_an_admin(user, removing=True)
    db.delete_user(user_id)
    return {"removed": user["username"]}

  def _bot(name: str) -> BotConnector:
    if name not in bots:
      raise HTTPException(404, f"unknown bot {name}")
    return bots[name]

  # ===========================================================================
  # MANAGE BOTS: add / edit / remove the ui's own bots (config.yaml ones are read only), live, no restart
  # ===========================================================================
  def _may_edit(request: Request) -> str | None:
    # none when allowed, else why not
    if config.bot_editing == "off":
      return "bot editing is off (bot_editing in config.yaml)"
    proxied = any(header in request.headers for header in ("x-forwarded-for", "forwarded", "tailscale-user-login"))
    local = not proxied and request.client is not None and request.client.host in ("127.0.0.1", "::1", "localhost")
    if config.bot_editing == "local" and not local:
      return "bots can only be changed from this machine (bot_editing: network in config.yaml allows it from others)"
    return None

  def _guard(request: Request) -> None:
    why = _may_edit(request)
    if why:
      raise HTTPException(403, why)

  def _ui_cfg(name: str) -> BotConfig:
    for bot_config in ui_bots.load():
      if bot_config.name == name:
        return bot_config
    raise HTTPException(404 if name not in from_config else 403, f"{name} is not a bot added here")

  def _new_cfg(body: dict, old: BotConfig | None = None) -> BotConfig:
    try:
      return BotConfig(
        name=str(body.get("name") or (old.name if old else "")).strip(),
        url=str(body.get("url") or "").strip(),
        username=str(body.get("username") or "").strip(),
        password=body.get("password") or (old.password if old else None),
        trading=bool(body["trading"]) if "trading" in body else (old.trading if old else False),
        radar=bool(body["radar"]) if "radar" in body else (old.radar if old else False),
        container=str(body["container"]) if "container" in body else (old.container if old else None),
      )
    except ValidationError as e:
      raise HTTPException(
        422, "; ".join(f"{'.'.join(map(str, problem['loc']))}: {problem['msg']}" for problem in e.errors())
      ) from e

  async def _start(bot_config: BotConfig) -> None:
    connector = _connector(bot_config)
    bots[bot_config.name] = connector
    await connector.start()
    hub.publish({"type": "state_diff", "bot": bot_config.name, "data": connector.state})

  async def _stop(name: str) -> None:
    connector = bots.pop(name, None)
    if connector:
      await connector.stop()
      hub.publish({"type": "bot_removed", "bot": name})

  @app.get("/api/manage/bots")
  async def manage_list(request: Request):
    ui_names = {ui_bot.name for ui_bot in ui_bots.load()}
    rows = [
      {
        "name": name,
        "url": connector.bot.url,
        "username": connector.bot.username,
        "source": "ui" if name in ui_names else "config",
        "trading": connector.bot.trading,
        "radar": connector.bot.radar,
        "container": connector.bot.container,
      }
      for name, connector in bots.items()
    ]
    return {"why_not": _may_edit(request), "write_actions": config.write_actions, "bots": rows}

  @app.post("/api/manage/bots/test")
  async def manage_test(body: dict, request: Request):
    _guard(request)
    old = next((ui_bot for ui_bot in ui_bots.load() if ui_bot.name == body.get("name")), None)
    bot_config = _new_cfg({**body, "name": body.get("name") or "test"}, old)
    client = FreqtradeClient(bot_config, timeout=8)
    try:
      await client.login()
      return {"ok": True, "message": "login works"}
    except AuthError:
      return {"ok": False, "message": "freqtrade rejected that username / password"}
    except (httpx.HTTPError, OSError) as e:
      return {"ok": False, "message": f"can't reach {bot_config.url} ({type(e).__name__})"}
    finally:
      await client.close()

  @app.post("/api/manage/bots")
  async def manage_add(body: dict, request: Request):
    _guard(request)
    bot_config = _new_cfg(body)
    if bot_config.name in bots or bot_config.name in from_config:
      raise HTTPException(409, f"a bot called {bot_config.name} already exists")
    ui_bots.save([*ui_bots.load(), bot_config])
    await _start(bot_config)
    return {"name": bot_config.name}

  @app.put("/api/manage/bots/{name}")
  async def manage_edit(name: str, body: dict, request: Request):
    _guard(request)
    old = _ui_cfg(name)
    bot_config = _new_cfg(body, old)  # empty password keeps the old one
    if bot_config.name != name and (bot_config.name in bots or bot_config.name in from_config):
      raise HTTPException(409, f"a bot called {bot_config.name} already exists")
    ui_bots.save([bot_config if ui_bot.name == name else ui_bot for ui_bot in ui_bots.load()])
    await _stop(name)
    await _start(bot_config)
    return {"name": bot_config.name}

  @app.delete("/api/manage/bots/{name}")
  async def manage_remove(name: str, request: Request):
    _guard(request)
    _ui_cfg(name)
    ui_bots.save([ui_bot for ui_bot in ui_bots.load() if ui_bot.name != name])
    await _stop(name)
    return {"removed": name}

  # what nfiforge keeps for a bot, and clearing it (a bot started on a fresh database); admins only (middleware).
  # every bot, config.yaml ones too: this is nfiforge's data, not the bot's settings
  @app.get("/api/manage/bots/{name}/data")
  async def manage_data(name: str):
    connector = _bot(name)
    counts = await asyncio.to_thread(db.bot_data, name)
    return {
      "fresh_db": connector.state["fresh_db"],
      "counts": counts | {"logs": len(connector.logs_kept) + len(connector.logs_debug)},
    }

  @app.post("/api/manage/bots/{name}/reset")
  async def manage_reset(name: str, body: dict):
    connector = _bot(name)
    parts = [part for part in body.get("parts") or [] if part in (*db.BOT_PARTS, "logs")]
    gone = await asyncio.to_thread(db.reset_bot, name, parts)
    if "logs" in parts:
      gone["logs"] = len(connector.logs_kept) + len(connector.logs_debug)
      connector.clear_logs()
    if "radar" in parts and connector.radar:
      connector.radar = Radar(db, name)
    await connector.sync_history(True)  # remembers the database as it is now: the fresh-database warning goes
    return {"cleared": gone}

  # ===========================================================================
  # TRADE ACTIONS: admins only (middleware), write_actions in config.yaml + the bot's own trading switch. the bot's
  # dry_run is asked fresh each time; a live bot needs the pair typed back. every action is logged as a notification
  # ===========================================================================
  def _trading_bot(name: str) -> BotConnector:
    connector = _bot(name)
    if not config.write_actions:
      raise HTTPException(403, "trade actions are off (write_actions: true in config.yaml turns them on)")
    if not connector.bot.trading:
      raise HTTPException(403, f"trading is off for {name} (turn it on in Manage Bots)")
    return connector

  def _bot_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
      try:
        body = e.response.json()
        return str(body.get("error") or body.get("detail") or body)
      except ValueError:
        return f"HTTP {e.response.status_code}"
    return f"{type(e).__name__}: {e}"

  # accept: what may be typed back on a live bot (coin or pair for trades, the bot's name for bot control)
  async def _live_check(connector: BotConnector, body: dict, accept: tuple[str, ...]) -> bool:
    try:
      live = (await connector.client.get("/show_config")).get("dry_run") is not True  # unknown counts as live
    except Exception as e:
      raise HTTPException(502, f"can't check if {connector.bot.name} is live: {_bot_error(e)}") from e
    typed = str(body.get("confirm") or "").strip().upper()
    if live and typed not in {answer.upper() for answer in accept}:
      raise HTTPException(428, f"{connector.bot.name} trades real money: type {accept[0]} to confirm")
    return live

  def _coin(pair: str) -> tuple[str, str]:
    return pair.split("/")[0], pair

  async def _trade_action(
    request: Request,
    body: dict,
    connector: BotConnector,
    what: str,
    target: str,
    method: str,
    path: str,
    payload: dict | list,
    accept: tuple[str, ...],
  ):
    live = await _live_check(connector, body, accept)
    who = request.state.user["username"]
    title = f"{who}: {what} {target}".rstrip() + (" (live)" if live else "")
    try:
      result = await connector.client.act(method, path, payload or None)
    except Exception as e:
      error = _bot_error(e)
      hub.publish(
        {
          "type": "notification",
          "data": db.add_note(
            connector.bot.name, "action", "bad", path, f"{title} failed", f"{error} · sent {json.dumps(payload)}"
          ),
        }
      )
      raise HTTPException(502, f"{connector.bot.name}: {error}") from e
    # freqtrade answers a refused force entry with 200 and an error status, a refused blacklist entry with errors
    errors = result.get("errors") if isinstance(result, dict) else None
    bad = (
      result["status"]
      if isinstance(result, dict) and str(result.get("status") or "").startswith("Error")
      else "; ".join(
        f"{key}: {value.get('error_msg', value) if isinstance(value, dict) else value}" for key, value in errors.items()
      )
      if isinstance(errors, dict) and errors
      else str(errors)
      if errors
      else None
    )
    failed = bad is not None
    level, detail = (
      ("bad", bad)
      if failed
      else ("info", str(result.get("result") or result.get("status") or "") if isinstance(result, dict) else "")
    )
    note = db.add_note(
      connector.bot.name,
      "action",
      level,
      path,
      f"{title}{' failed' if failed else ''}",
      " · ".join(part for part in (detail, f"sent {json.dumps(payload)}") if part),
    )
    hub.publish({"type": "notification", "data": note})
    if failed:
      raise HTTPException(502, f"{connector.bot.name}: {bad}")
    return result

  def _positive_number(body: dict, key: str) -> float | None:
    value = body.get(key)
    if value in (None, ""):
      return None
    try:
      number = float(value)
    except (TypeError, ValueError):
      number = 0
    if not (number > 0 and math.isfinite(number)):
      raise HTTPException(422, f"{key} must be a number above 0")
    return number

  def _ordertype(body: dict) -> str | None:
    value = body.get("ordertype") or None
    if value not in (None, "market", "limit"):
      raise HTTPException(422, "ordertype: market or limit")
    return value

  async def _open_trade(connector: BotConnector, body: dict) -> dict:
    try:
      trade_id = int(body.get("tradeid"))
      trade = await connector.client.get(f"/trade/{trade_id}")
    except (TypeError, ValueError) as e:
      raise HTTPException(422, "tradeid must be a number") from e
    except httpx.HTTPStatusError as e:
      raise HTTPException(404, f"no trade {body.get('tradeid')} on {connector.bot.name}") from e
    except httpx.HTTPError as e:
      raise HTTPException(502, f"can't reach {connector.bot.name}: {_bot_error(e)}") from e
    if not trade.get("is_open"):
      raise HTTPException(409, f"trade {trade_id} is already closed")
    return trade

  # new trade, or an add to an open one (same pair and side; the entry tag becomes the order's tag, so nfi v4 counts
  # an add tagged grind_2_entry as grind 2)
  @app.post("/api/trade/{name}/enter")
  async def trade_enter(name: str, body: dict, request: Request):
    connector = _trading_bot(name)
    pair, side = str(body.get("pair") or "").strip(), body.get("side") or "long"
    if not pair or side not in ("long", "short"):
      raise HTTPException(422, "pair and side (long or short) are needed")
    tag = str(body.get("entry_tag") or "force_entry").strip()
    if len(tag) > 64:
      raise HTTPException(422, "entry tag is too long")
    payload = {"pair": pair, "side": side, "entry_tag": tag, "ordertype": _ordertype(body)}
    payload |= {key: _positive_number(body, key) for key in ("price", "stakeamount", "leverage")}
    # an add with no stake gets a whole new trade's stake (the strategy's sizing only runs on a first entry)
    holds = any(trade.get("pair") == pair for trade in connector.state["status"] or [])
    if holds and not payload.get("stakeamount"):
      raise HTTPException(422, f"{connector.bot.name} already holds {pair}: give a stake for the add")
    payload = {key: value for key, value in payload.items() if value is not None}
    return await _trade_action(
      request, body, connector, f"enter {side} ({tag})", pair, "POST", "/forceenter", payload, accept=_coin(pair)
    )

  # full exit, or partial with an amount in coins
  @app.post("/api/trade/{name}/exit")
  async def trade_exit(name: str, body: dict, request: Request):
    connector = _trading_bot(name)
    trade = await _open_trade(connector, body)
    amount = _positive_number(body, "amount")
    if amount and amount >= trade["amount"]:
      amount = None  # all of it
    payload = {
      "tradeid": str(trade["trade_id"]),
      "ordertype": _ordertype(body),
      "amount": amount,
      "price": _positive_number(body, "price"),
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    what = f"partial exit {amount:g} of {trade['amount']:g}" if amount else "exit"
    return await _trade_action(
      request, body, connector, what, trade["pair"], "POST", "/forceexit", payload, accept=_coin(trade["pair"])
    )

  @app.post("/api/trade/{name}/cancel")
  async def trade_cancel(name: str, body: dict, request: Request):
    connector = _trading_bot(name)
    trade = await _open_trade(connector, body)
    return await _trade_action(
      request,
      body,
      connector,
      "cancel open order",
      trade["pair"],
      "DELETE",
      f"/trades/{trade['trade_id']}/open-order",
      {},
      accept=_coin(trade["pair"]),
    )

  @app.post("/api/trade/{name}/reload")
  async def trade_reload(name: str, body: dict, request: Request):
    connector = _trading_bot(name)
    trade = await _open_trade(connector, body)
    return await _trade_action(
      request,
      body,
      connector,
      "reload from exchange",
      trade["pair"],
      "POST",
      f"/trades/{trade['trade_id']}/reload",
      {},
      accept=_coin(trade["pair"]),
    )

  # removes the trade from the bot's database only; the position stays open on the exchange
  @app.post("/api/trade/{name}/delete")
  async def trade_delete(name: str, body: dict, request: Request):
    connector = _trading_bot(name)
    trade = await _open_trade(connector, body)
    return await _trade_action(
      request,
      body,
      connector,
      "delete trade",
      trade["pair"],
      "DELETE",
      f"/trades/{trade['trade_id']}",
      {},
      accept=_coin(trade["pair"]),
    )

  # bot control: pause = no new entries (open trades still managed), start = resume, stop = the bot loop stops (open
  # trades not managed), reload_config = re-read config + strategy. on a live bot the bot's name is typed back
  CONTROL = {"pause": "pause entries", "start": "start", "stop": "stop", "reload_config": "reload config"}

  @app.post("/api/trade/{name}/control")
  async def trade_control(name: str, body: dict, request: Request):
    connector = _trading_bot(name)
    action = body.get("action")
    if action not in CONTROL:
      raise HTTPException(422, "action: pause, start, stop or reload_config")
    result = await _trade_action(
      request, body, connector, CONTROL[action], "", "POST", f"/{action}", {}, accept=(connector.bot.name,)
    )
    # show the new state now instead of at the next config poll
    with contextlib.suppress(Exception):
      await connector.refresh_config()
    return result

  # pair locks: lock a pair (or "*" = every pair) for some minutes, or remove a lock. the bot's name is typed on a
  # live bot for "*", the coin otherwise
  @app.post("/api/trade/{name}/lock")
  async def trade_lock(name: str, body: dict, request: Request):
    connector = _trading_bot(name)
    pair, side = str(body.get("pair") or "").strip(), body.get("side") or "*"
    if not pair or side not in ("*", "long", "short"):
      raise HTTPException(422, "pair and side (*, long or short) are needed")
    minutes = _positive_number(body, "minutes")
    if not minutes or minutes > 525600:
      raise HTTPException(422, "minutes: above 0, at most a year")
    reason = str(body.get("reason") or "").strip()[:100] or "locked from NFIForge"
    until = datetime.now(UTC) + timedelta(minutes=minutes)
    payload = [{"pair": pair, "side": side, "until": until.isoformat(), "reason": reason}]
    accept = (connector.bot.name,) if pair == "*" else _coin(pair)
    what = f"lock {side if side != '*' else ''} {minutes:g} min".replace("  ", " ")
    result = await _trade_action(request, body, connector, what, pair, "POST", "/locks", payload, accept=accept)
    connector._set("locks", result)
    return result

  @app.post("/api/trade/{name}/unlock")
  async def trade_unlock(name: str, body: dict, request: Request):
    connector = _trading_bot(name)
    locks = (connector.state["locks"] or {}).get("locks") or []
    lock = next((item for item in locks if str(item.get("id")) == str(body.get("lockid"))), None)
    if not lock:
      raise HTTPException(404, f"no lock {body.get('lockid')} on {name}")
    accept = (connector.bot.name,) if lock["pair"] == "*" else _coin(lock["pair"])
    result = await _trade_action(
      request, body, connector, "unlock", lock["pair"], "DELETE", f"/locks/{lock['id']}", {}, accept=accept
    )
    connector._set("locks", result)
    return result

  # blacklist: add or remove one entry (a pair, or a pattern like .*DOWN/USDT). the entry itself is typed on a live bot
  @app.post("/api/trade/{name}/blacklist")
  async def trade_blacklist(name: str, body: dict, request: Request):
    connector = _trading_bot(name)
    entry, action = str(body.get("pair") or "").strip(), body.get("action")
    if not entry or len(entry) > 64 or action not in ("add", "remove"):
      raise HTTPException(422, "pair (or pattern) and action (add or remove) are needed")
    accept = (*_coin(entry), entry)
    if action == "add":
      result = await _trade_action(
        request, body, connector, "blacklist", entry, "POST", "/blacklist", {"blacklist": [entry]}, accept=accept
      )
    else:
      if entry not in ((connector.state["blacklist"] or {}).get("blacklist") or []):
        raise HTTPException(404, f"{entry} isn't on {name}'s blacklist")
      path = f"/blacklist?{urlencode({'pairs_to_delete': entry})}"
      result = await _trade_action(
        request, body, connector, "remove from blacklist", entry, "DELETE", path, {}, accept=accept
      )
    with contextlib.suppress(Exception):
      await connector.refresh("blacklist", "/blacklist")
    return result

  # ===========================================================================
  # SHARING: results in percent only (share.py). share links for anyone with the code, made by admins under
  # /api/manage/; /api/view is the same page for percent-only viewers
  # ===========================================================================
  share_limit = RateLimit(limit=60, window=60)  # requests per address per minute on share links
  NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}

  @app.get("/api/manage/shares")
  async def shares_list():
    return [share.row(record) for record in db.shares()]

  @app.post("/api/manage/shares")
  async def shares_add(body: dict):
    try:
      cleaned = share.clean(body, list(bots))
    except ValueError as e:
      raise HTTPException(422, str(e)) from e
    code, code_hash = new_secret()
    expires = time.time() + cleaned["days"] * 86400 if cleaned["days"] else None
    share_id = db.add_share(code_hash, cleaned["name"], cleaned["bots"], cleaned["opts"], expires)
    # the only time the code is shown: the link can't be read back later, only revoked
    return {"id": share_id, "code": code, "path": f"/s/{code}"}

  @app.delete("/api/manage/shares/{share_id}")
  async def shares_drop(share_id: int):
    if not db.drop_share(share_id):
      raise HTTPException(404, "no such share link")
    return {"ok": True}

  @app.get("/api/share/{code}")
  async def share_page(code: str, request: Request):
    who = request.client.host if request.client else "?"
    if limiter_wait := share_limit.blocked(who):
      raise HTTPException(429, f"too many requests, try again in {limiter_wait:.0f} s")
    share_limit.fail(who)
    record = db.share_by_code(digest(code)) if 20 <= len(code) <= 100 else None
    if not record:
      await asyncio.sleep(0.3)  # wrong, revoked and expired codes all look the same
      return JSONResponse({"detail": "this link doesn't work (revoked or expired)"}, status_code=404, headers=NO_STORE)
    shared = share.row(record)
    return JSONResponse(share.view(bots, shared["bots"], shared["opts"], shared["name"]), headers=NO_STORE)

  @app.get("/api/view")
  async def percent_view(request: Request):
    access = request.state.access
    return share.view(bots, [name for name in bots if access.bot(name)], dict.fromkeys(share.OPTS, True))

  @app.get("/api/health")
  async def health():
    return {
      "ok": True,
      "version": __version__,
      "bots": len(bots),
      "btcgate": gate is not None,
      "orderflow": flow is not None,
    }

  @app.get("/api/bots")
  async def list_bots(request: Request):
    return [
      {
        key: connector.state[key]
        for key in ("name", "connected", "ws_connected", "error", "is_nfi", "version", "latency_ms")
      }
      | {"strategy": (connector.state["config"] or {}).get("strategy")}
      for connector in bots.values()
      if request.state.access.bot(connector.bot.name)
    ]

  @app.get("/api/bots/{name}/state")
  async def bot_state(name: str):
    return _bot(name).state

  @app.get("/api/bots/{name}/events")
  async def bot_events(name: str, limit: int = 100):
    return list(_bot(name).events)[-limit:]

  # every closed trade of a bot (filtered and paged in the browser)
  @app.get("/api/bots/{name}/history")
  async def bot_history(name: str):
    return sorted(_bot(name).history.values(), key=lambda trade: trade.get("close_timestamp") or 0, reverse=True)

  # exchange candles: around a trade (inspector) or, with a timeframe, the latest `limit` candles (chart page)
  @app.get("/api/bots/{name}/candles")
  async def bot_candles(
    name: str, pair: str, start: float = 0, end: float = 0, timeframe: str | None = None, limit: int = 1000
  ):
    bot_config = _bot(name).state["config"] or {}
    if not bot_config.get("exchange"):
      raise HTTPException(503, "bot config not loaded yet")
    if timeframe and start and timeframe not in TF_SEC:
      raise HTTPException(400, f"timeframe must be one of {', '.join(TF_SEC)}")
    try:
      futures = bot_config.get("trading_mode") == "futures"
      if timeframe and not start:
        return await market.latest(bot_config["exchange"], futures, pair, timeframe, min(limit, 1500))
      return await market.candles(bot_config["exchange"], futures, pair, start, end, timeframe)
    except Exception as e:
      raise HTTPException(502, f"exchange candles failed: {type(e).__name__}: {e}") from e

  # signal radar (bots with radar on): signals and guard columns per candle over the last `hours` (up to 7 days),
  # what happened to each signal
  @app.get("/api/bots/{name}/radar")
  async def bot_radar(name: str, hours: float = 24):
    connector = _bot(name)
    if not connector.radar:
      return {"enabled": False}
    trades = {trade["trade_id"]: trade for trade in connector.history.values()} | {
      trade["trade_id"]: trade for trade in connector.state["status"] or []
    }
    since = time.time() - min(max(hours, 1), 168) * 3600
    return connector.radar.view(connector.state, list(trades.values()), list(connector.logs_kept), since=since)

  # best / worst move of each closed trade, as far as measured: {trade_id: [mfe %, mae %]} (null = can't be measured)
  @app.get("/api/bots/{name}/excursions")
  async def bot_excursions(name: str):
    bot = _bot(name)
    kept = await asyncio.to_thread(db.excursions, name)
    closed = [trade for trade in bot.history.values() if not trade.get("is_open")]
    rows = {
      str(trade["trade_id"]): kept[key]
      for trade in closed
      if (key := (trade["trade_id"], trade.get("open_timestamp"))) in kept
    }
    return {"rows": rows, "done": len(rows), "total": len(closed)}

  # live price from the exchange (public ticker, no keys), for the trade forms
  @app.get("/api/bots/{name}/ticker")
  async def bot_ticker(name: str, pair: str):
    bot_config = _bot(name).state["config"] or {}
    if not bot_config.get("exchange"):
      raise HTTPException(503, "bot config not loaded yet")
    try:
      return await market.ticker(bot_config["exchange"], bot_config.get("trading_mode") == "futures", pair)
    except Exception as e:
      raise HTTPException(502, f"exchange price failed: {type(e).__name__}: {e}") from e

  # usdt in a real currency, for showing equity and p&l in it; rate is None when no fresh one
  @app.get("/api/fx/{currency}")
  async def fx_rate(currency: str):
    try:
      return {"rate": await fx_rates.rate(currency)}
    except ValueError as e:
      raise HTTPException(400, str(e)) from e

  # the bot's analysed frame for a pair: candles plus any indicator columns the strategy made
  @app.get("/api/bots/{name}/frame")
  async def bot_frame(name: str, pair: str, columns: str = "", limit: int = 1000):
    cols = ["__date_ts", "open", "high", "low", "close", "volume"] + [column for column in columns.split(",") if column]
    try:
      return await _bot(name).frame(pair, min(limit, 1500), list(dict.fromkeys(cols)))
    except httpx.HTTPStatusError as e:
      raise HTTPException(502, f"bot has no candles for {pair}: {e.response.status_code}") from e

  # column names of the bot's frame (one candle asked for, every column), for the indicator picker
  @app.get("/api/bots/{name}/frame/columns")
  async def bot_frame_columns(name: str, pair: str):
    try:
      frame = await _bot(name).frame(pair, 1)
    except httpx.HTTPStatusError as e:
      raise HTTPException(502, f"bot has no candles for {pair}: {e.response.status_code}") from e
    base = ("date", "open", "high", "low", "close", "volume")
    return [column for column in frame["columns"] if not column.startswith("__") and column not in base]

  # the bot's log lines kept since nfiforge started; [date, ts, logger, level, message], tokens masked
  @app.get("/api/bots/{name}/logs")
  async def bot_logs(name: str, limit: int = 20000, debug: bool = False):
    return _bot(name).logs(min(limit, 20000), debug)

  # server history (host, containers, bot loop times), one point a minute
  @app.get("/api/server/history")
  async def server_history(hours: float = 24):
    return await asyncio.to_thread(db.server_history, time.time() - min(hours, 24 * 30) * 3600)

  # notifications, newest first; read marker shared by every browser
  @app.get("/api/notifications")
  async def notifications(request: Request, limit: int = 200, before: int | None = None, kind: str | None = None):
    seen = _notes_seen(request.state.access)
    return {
      "items": db.notes(min(limit, 1000), before, kind, **seen),
      "active": db.notes(1000, active=True, **seen),
      "unread": db.unread(**seen),
      "read": db.read_marker(),
    }

  def _notes_seen(access: Access) -> dict:
    return {"bots": access.bots, "host": access.page("server")}

  @app.post("/api/notifications/read")
  async def notifications_read(body: dict, request: Request):
    try:
      note_id = int(body.get("id") or 0)
    except (TypeError, ValueError) as e:
      raise HTTPException(422, "id must be a number") from e
    db.set_read(note_id)
    hub.publish({"type": "notifications_read", "data": {"read": db.read_marker(), "unread": db.unread()}})
    return {"unread": db.unread(**_notes_seen(request.state.access))}

  # pairlist view: whitelist, blacklist, locks, changes, filtered-out reasons
  @app.get("/api/bots/{name}/pairs")
  async def bot_pairs(name: str):
    return _bot(name).pairs()

  # bot health checks for a bot
  @app.get("/api/bots/{name}/checks")
  async def bot_checks(name: str):
    bot = _bot(name)
    freqtrade_latest = (await latest_release("freqtrade/freqtrade")).get("tag_name") if config.update_check else None
    return {
      "config": bot.state["config"],
      "version": bot.state["version"],
      "checks": checks(bot.state, *bot.log_flags(), freqtrade_latest),
    }

  # the strategy's own plot_config (indicators it suggests showing)
  @app.get("/api/bots/{name}/plot_config")
  async def bot_plot_config(name: str):
    try:
      return await _bot(name).client.get("/plot_config")
    except httpx.HTTPStatusError:
      return {}

  @app.get("/api/update")
  async def update_info():
    return await check_update(config.update_check)

  @app.get("/api/host")
  async def host_state():
    return host.state

  @app.get("/api/bots/{name}/equity")
  async def bot_equity(name: str, hours: float = 24):
    _bot(name)
    return await asyncio.to_thread(db.equity, name, time.time() - hours * 3600)

  @app.get("/api/settings")
  async def get_settings():
    return store.settings

  # dashboard's own settings, not a trading action, so not behind write_actions
  @app.put("/api/settings")
  async def put_settings(s: Settings):
    try:
      orderflow_settings = _orderflow(s.orderflow)
    except ValidationError as e:
      raise HTTPException(422, f"order flow: {e.errors()[0]['loc'][0]}: {e.errors()[0]['msg']}") from e
    saved = store.save(s)
    if flow is not None:  # the worker reads its options again within 30 s; memory at its next check
      flow.settings.update(orderflow_settings.model_dump(exclude={"enabled", "memory_mb"}))
      flow.memory_mb = orderflow_settings.memory_mb
    hub.publish({"type": "settings", "data": saved.model_dump()})
    return saved

  @app.websocket("/ws")
  async def ws(websocket: WebSocket):
    session_id = websocket.cookies.get(COOKIE)
    if not (user := await asyncio.to_thread(_session_user, session_id)):
      await websocket.close(code=4401)
      return
    if (access := Access(user)).percent:  # the percent view polls its own answer; live state carries amounts
      await websocket.close(code=4403)
      return
    await websocket.accept()
    queue = hub.subscribe()
    try:
      # with the events kept so far, so the event stream isn't empty after a reload. only the user's bots
      mine = {name: connector for name, connector in bots.items() if access.bot(name)}
      await websocket.send_json(
        {
          "type": "snapshot",
          "data": {name: connector.state for name, connector in mine.items()},
          "events": {name: list(connector.events) for name, connector in mine.items()},
        }
      )
      if access.page("server"):
        await websocket.send_json({"type": "host", "data": host.state})
      checked = time.monotonic()
      while True:
        # a signed out, blocked or removed user's open socket closes within 30 s; changed access applies then too
        if time.monotonic() - checked > 30:
          if not (user := await asyncio.to_thread(_session_user, session_id)) or (access := Access(user)).percent:
            await websocket.close(code=4401)
            return
          checked = time.monotonic()
        with contextlib.suppress(TimeoutError):
          msg = await asyncio.wait_for(queue.get(), 30)
          if not access.message(msg):
            continue
          if msg["type"] == "notifications_read" and not access.admin:  # the count of what this user sees
            msg = {**msg, "data": {**msg["data"], "unread": db.unread(**_notes_seen(access))}}
          await websocket.send_json(msg)
    except WebSocketDisconnect:
      pass
    finally:
      hub.unsubscribe(queue)

  if gate:
    from nfiforge.btcgate.routes import router as btcgate_router

    app.include_router(btcgate_router(gate))

  if flow:
    from nfiforge.orderflow.routes import router as orderflow_router

    def _bot_market(name: str) -> tuple[str, str]:
      bot_config = _bot(name).state["config"] or {}
      if not bot_config.get("exchange"):
        raise HTTPException(503, "bot config not loaded yet")
      return bot_config["exchange"], "swap" if bot_config.get("trading_mode") == "futures" else "spot"

    app.include_router(orderflow_router(flow, _bot_market))

  # built web ui (docker image / pip package); in development vite serves it instead
  web = Path(os.environ.get("NFIFORGE_WEB", Path(__file__).parent / "web"))
  if (web / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

    # any other non-api path is a page of the single-page app
    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
      if path.startswith("api/"):
        raise HTTPException(404, "no such api route")
      root = os.path.realpath(web)
      file_path = os.path.realpath(os.path.join(root, path))
      if path and file_path.startswith(root + os.sep) and os.path.isfile(file_path):
        return FileResponse(file_path)
      return FileResponse(web / "index.html")

  return app
