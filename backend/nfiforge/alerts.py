# notifications: nfiforge's own alerts (raised while a condition holds, cleared when it goes away) and the bot's
# trade events, kept in the store and pushed to open browsers

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from nfiforge.settings import AlertSettings
from nfiforge.store import Store

log = logging.getLogger(__name__)


# ===========================================================================
# ALERT RULES: (key, level, title, detail) for every condition that holds now
# ===========================================================================
def conditions(
  name: str, bot_state: dict[str, Any], alert_settings: AlertSettings, now: float
) -> list[tuple[str, str, str, str]]:
  out = []
  if not bot_state.get("connected"):
    return [("api", "bad", f"{name}: bot API not reachable", bot_state.get("error") or "")]
  if not bot_state.get("ws_connected"):
    out.append(("stream", "warn", f"{name}: live message stream down", "fills and exits arrive late"))
  state = (bot_state.get("config") or {}).get("state")
  if state and state != "running":
    out.append(("state", "bad", f"{name}: bot is {state}", "no new trades are opened"))
  last = (bot_state.get("health") or {}).get("last_process_ts")
  if last and now - last > alert_settings.stuck_min * 60:
    out.append(("stuck", "bad", f"{name}: no bot loop for {(now - last) / 60:.0f} min", "the bot may be stuck"))
  for trade in bot_state.get("status") or []:
    liq, rate = trade.get("liquidation_price"), trade.get("current_rate")
    if liq and rate:
      distance = abs(rate - liq) / rate * 100
      if distance < alert_settings.liq_pct:
        side = "short" if trade.get("is_short") else "long"
        out.append(
          (
            f"liq:{trade.get('trade_id')}",
            "bad",
            f"{name}: {trade.get('pair')} {side} is {distance:.1f} % from liquidation",
            f"price {rate}, liquidation {liq}",
          )
        )
  if bot_state.get("fresh_db"):
    out.append(
      (
        "fresh_db",
        "warn",
        f"{name}: looks like a new trade database",
        "its old trades are gone; Manage Bots > reset data clears what NFIForge kept from before",
      )
    )
  drawdown = ((bot_state.get("profit") or {}).get("current_drawdown") or 0) * 100
  if drawdown > alert_settings.drawdown_pct:
    out.append(
      ("drawdown", "warn", f"{name}: drawdown {drawdown:.1f} %", f"above your {alert_settings.drawdown_pct:g} % alert")
    )
  return out


# server: host disk / ram, containers near their memory limit, out-of-memory kills and restarts (shown 15 min)
def server_conditions(
  host: dict[str, Any], alert_settings: AlertSettings, recent: dict[str, tuple[str, float]], now: float
) -> list:
  out = []
  if (host.get("disk") or 0) > alert_settings.disk_pct:
    free = (host.get("disk_free") or 0) / 2**30
    out.append(("disk", "bad", f"Server disk {host['disk']:.0f} % full", f"{free:.1f} GB free"))
  if (host.get("ram") or 0) > alert_settings.ram_pct:
    out.append(("ram", "warn", f"Server RAM {host['ram']:.0f} % used", "bots may get killed when it runs out"))
  for container in host.get("containers") or []:
    if (
      container.get("mem")
      and container.get("mem_max")
      and container["mem"] / container["mem_max"] * 100 > alert_settings.container_mem_pct
    ):
      pct = container["mem"] / container["mem_max"] * 100
      out.append(
        (f"cmem:{container['id']}", "warn", f"{container['label']} at {pct:.0f} % of its memory limit", container["id"])
      )
  for key, (title, raised_at) in recent.items():
    if now - raised_at < 900:
      out.append((key, "bad" if key.startswith("oom") else "warn", title, ""))
  return out


# how long a condition must hold before it alerts (a blip shouldn't wake anyone)
def hold_for(key: str, alert_settings: AlertSettings) -> float:
  return alert_settings.api_down_s if key == "api" else 120 if key == "stream" else 0


# ===========================================================================
# TRADE EVENTS from freqtrade's message websocket
# ===========================================================================
def describe(msg_type: str, data: Any) -> tuple[str, str, str] | None:
  if not isinstance(data, dict):
    data = {"status": data}
  pair = data.get("pair", "")
  if msg_type in ("entry_fill", "exit_fill", "entry_cancel", "exit_cancel") and not pair:
    return None  # nothing useful to show
  side = (data.get("direction") or "").lower()
  leverage = f" {data['leverage']:g}x" if data.get("leverage") else ""
  if msg_type == "entry_fill":
    what = "added to" if data.get("sub_trade") else "opened"
    tag = f" · tag {data['enter_tag']}" if data.get("enter_tag") else ""
    return (
      "info",
      f"{pair} {side}{leverage} {what}",
      f"stake {data.get('stake_amount')} at {data.get('open_rate')}{tag}",
    )
  if msg_type == "exit_fill":
    profit = (data.get("profit_ratio") or 0) * 100
    what = "closed" if data.get("is_final_exit", not data.get("sub_trade")) else "partly sold"
    level = "ok" if profit >= 0 else "warn"
    return level, f"{pair} {side} {what} {profit:+.2f} %", f"{data.get('profit_amount')} · {data.get('exit_reason')}"
  if msg_type in ("entry_cancel", "exit_cancel"):
    return (
      "info",
      f"{pair} {'entry' if msg_type == 'entry_cancel' else 'exit'} order cancelled",
      data.get("reason") or "",
    )
  if msg_type in ("protection_trigger", "protection_trigger_global"):
    who = "all pairs" if msg_type.endswith("global") else pair or data.get("pair", "")
    return "warn", f"Protection locked {who}", f"{data.get('reason') or ''} until {data.get('lock_end_time') or ''}"
  if msg_type in ("warning", "exception"):
    return "warn", "Bot warning" if msg_type == "warning" else "Bot error", str(data.get("status") or data)
  if msg_type == "startup":
    return "info", "Bot started", str(data.get("status") or "")
  if msg_type == "strategy_msg":
    return "info", "Strategy message", str(data.get("msg") or data.get("status") or "")
  return None


class Notifier:
  def __init__(
    self,
    store: Store,
    settings: Callable[[], AlertSettings],
    publish: Callable[[dict], None],
    push: Callable[[dict], None] | None = None,
  ) -> None:
    self.store = store
    self.settings = settings
    self.publish = publish
    self.push = push  # phone alerts: alerts only, trade events stay on the page
    # alerts still open from a previous run: re-checked on the first pass, cleared if fine
    self.active: dict[tuple[str, str], dict] = {
      (note["bot"], note["key"]): note for note in store.notes(1000, active=True)
    }
    self.since: dict[tuple[str, str], float] = {}
    self._counts: dict[str, tuple[int, int]] = {}  # container id -> (oom kills, restarts) last seen
    self._recent: dict[str, tuple[str, float]] = {}  # key -> (title, when) for kills / restarts just seen

  def _emit(self, note: dict) -> None:
    self.publish({"type": "notification", "data": note})
    if self.push and note.get("kind") == "alert":
      self.push(note)

  def trade_event(self, bot: str, msg_type: str, data: Any) -> None:
    if not self.settings().trade_events:
      return
    described = describe(msg_type, data)
    if described:
      self._emit(self.store.add_note(bot, "trade", described[0], msg_type, described[1], described[2]))

  def btcgate_signal(self, row: dict, label: str, meaning: str) -> None:
    coin = row["pair"].split("/")[0]
    price = f" at {row['price']:.6g}" if row.get("price") else ""
    kind = f" ({row['kind']})" if row.get("kind") else ""
    detail = meaning + kind + price
    level = "warn" if row["signal"] == "lock" else "info"
    note = self.store.add_note("BTCGate", "signal", level, f"{row['signal']}:{coin}", f"{label}: {coin}", detail)
    self.publish({"type": "notification", "data": note})
    if self.push and row.get("push"):
      self.push(note)

  def _note_counts(self, host: dict[str, Any], now: float) -> None:
    for container in host.get("containers") or []:
      previous = self._counts.get(container["id"])
      if previous and container["oom_kills"] > previous[0]:
        self._recent[f"oom:{container['id']}"] = (f"{container['label']}: process killed, out of memory", now)
      if previous and container["restarts"] > previous[1]:
        self._recent[f"restart:{container['id']}"] = (f"{container['label']} restarted", now)
      self._counts[container["id"]] = (container["oom_kills"], container["restarts"])

  def check(self, bots: dict[str, Any], host: dict[str, Any] | None = None, now: float | None = None) -> None:
    now = now or time.time()
    alert_settings = self.settings()
    seen = set()
    found = [
      (name, *condition) for name, bot in bots.items() for condition in conditions(name, bot.state, alert_settings, now)
    ]
    if host:
      self._note_counts(host, now)
      found += [("Server", *condition) for condition in server_conditions(host, alert_settings, self._recent, now)]
    for name, key, level, title, detail in found:
      alert_key = (name, key)
      seen.add(alert_key)
      self.since.setdefault(alert_key, now)
      if alert_key not in self.active and now - self.since[alert_key] >= hold_for(key, alert_settings):
        self.active[alert_key] = self.store.add_note(name, "alert", level, key, title, detail)
        self._emit(self.active[alert_key])
    for alert_key in [alert_key for alert_key in self.active if alert_key not in seen]:
      note = self.active.pop(alert_key)
      self.store.clear_note(note["id"])
      self._emit(self.store.add_note(alert_key[0], "alert", "ok", alert_key[1], f"Resolved: {note['title']}", ""))
    for alert_key in [alert_key for alert_key in self.since if alert_key not in seen]:
      del self.since[alert_key]

  async def run(self, bots: dict[str, Any], host: Callable[[], dict[str, Any]], every: float = 15) -> None:
    await asyncio.sleep(every)  # let the bots connect first
    while True:
      try:
        self.check(bots, host())  # on the loop: publish isn't thread safe, the writes are tiny
      except Exception:
        log.exception("alert check failed")
      await asyncio.sleep(every)
