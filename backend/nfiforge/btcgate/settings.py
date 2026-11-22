# the btcgate settings page: which switches it shows (btcgate.json keys), what each one needs, and saving them.
# btcgate's own defaults apply to anything not in btcgate.json; the worker reports the settings it runs with
# (effective.json). keys and tokens go to btcgate_secret.json (owner-only) and are never sent back to a browser

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# (key, label, what it does, needs). needs: other switches, or "telegram" / "coinalyze" for a key or token
SECTIONS = [
  (
    "Labels",
    [
      ("trend.enabled", "Trend", "daily bull / neutral / bear per coin", []),
      ("turbulence.enabled", "Turbulence (day)", "volume spikes and funding extremes, normal / elevated / HIGH", []),
      ("turbulence.rolling", "Turbulence (24 h)", "the same over a rolling 24 h, every closed hour", []),
      ("flow.liquidations", "Direction: liquidations", "liquidation imbalance, one input of direction", ["coinalyze"]),
      ("flow.crowd", "Direction: crowd", "long / short accounts, one input of direction", ["coinalyze"]),
      ("flow.taker", "Direction: taker", "taker buy share, one input of direction", ["coinalyze"]),
      (
        "risk.enabled",
        "Big move risk",
        "chance of a big 4 h move",
        ["fast.enabled", "dvol.enabled", "calendar.us_open"],
      ),
    ],
  ),
  (
    "Fast signals",
    [
      ("fast.enabled", "Fast volume", "15 min volume spikes", []),
      ("fast.oi", "Fast open interest", "1 h open interest spikes", ["fast.enabled"]),
      ("fast.dir", "Catch-up calls", "a lagging coin's first spike while BTC rises", ["fast.enabled"]),
      ("footprint.enabled", "Footprint", "contested spikes from taker volume", ["fast.enabled"]),
      ("footprint.forced", "Forced moves", "drops / rises made by forced exits", ["footprint.enabled", "fast.oi"]),
    ],
  ),
  (
    "Calendar and volatility",
    [
      ("dvol.enabled", "DVOL", "BTC implied volatility: 6 h change and jumps", []),
      ("calendar.fomc", "FOMC", "Fed meeting days", []),
      ("calendar.us_open", "US open", "the US market open hours", []),
      ("calendar.unlocks", "Token unlocks", "days to the next big unlock", []),
    ],
  ),
  (
    "News",
    [
      ("announcements.enabled", "Exchange announcements", "delistings and monitoring tags lock the coin", []),
      ("announcements.upbit", "Upbit warnings", "", ["announcements.enabled"]),
      ("announcements.hacks", "Hack locks", "", ["announcements.enabled"]),
      ("announcements.flags", "Exchange warning flags", "information only", ["announcements.enabled"]),
      (
        "announcements.exploit_news",
        "Exploit news",
        "headlines matched to coins, information only",
        ["announcements.enabled"],
      ),
    ],
  ),
  (
    "Recording and scoring",
    [
      ("ledger.test_signals", "Signal ledger", "scores core64 / breakdown / random signals (Ledger tab)", []),
      ("liquidations.record", "Liquidations", "records Binance liquidations", []),
      ("liquidations.okx", "Liquidations: OKX", "", ["liquidations.record"]),
      ("liquidations.gate", "Liquidations: Gate", "", ["liquidations.record"]),
      ("efficacy.enabled", "Efficacy", "scores each label on matured outcomes, daily in the log", []),
      ("hl_archive.enabled", "Hyperliquid archive", "hourly perps snapshot", []),
      (
        "scanner.enabled",
        "Coin scanner",
        "Scanner tab: pumps, bleeds, coins nearing your bots' lists, recovery list",
        [],
      ),
      (
        "scanner.buyback",
        "Buybacks",
        "what each coin's protocol hands holders (buybacks, staking payouts) as % of its market cap a year, from "
        "DefiLlama daily: Coins tab and scanner. Information only, untested",
        [],
      ),
    ],
  ),
  (
    "Telegram",
    [
      ("calls.enabled", "Your calls", "/call trades from Telegram, scored", ["telegram"]),
    ],
  ),
]
SWITCHES = {key for _, items in SECTIONS for key, *_ in items}
# shown, not switchable: the worker can't use them yet
NOT_YET = [
  ("probes.enabled", "Probes", "dry trades: only in freqtrade, not the worker"),
]
# what the worker's engine is always given: probes need freqtrade; the book is nfiforge's own (worker.book), from
# the bots it is connected to, not btcgate's bot configs
OFF = {"book": {"enabled": False}, "probes": {"enabled": False}}
ALERT_TYPES = [
  ("forced_dump", "Forced dump", "a drop made by forced exits, tends to snap back within the hour"),
  ("forced_squeeze", "Forced squeeze", "a rise made by forced short exits, tends to fade within the hour"),
  ("catchup", "Catch-up", "a lagging coin's first spike while BTC rises, leans up"),
  ("lock", "Lock", "exchange news against the coin (delisting, tag, hack)"),
  (
    "scanner",
    "Scanner",
    "a coin newly flagged (pump, volatile, 7 day move, nearing your bots' lists); Telegram: + daily recovery list",
  ),
  ("book", "Book", "a bot's likely 24 h swing above your limit, or many trades behaving like few bets (Book tab)"),
]
SECRETS = {
  "coinalyze_api_key": ("flow", "coinalyze_api_key"),
  "telegram_token": ("alerts", "telegram_token"),
  "chat_id": ("alerts", "chat_id"),
}


class Alerts(BaseModel):
  enabled: bool
  signals: list[str]
  coins: list[str] = Field(default_factory=list, max_length=300)  # empty = every watched coin
  cooldown_min: int = Field(60, ge=1, le=1440)

  @field_validator("signals")
  @classmethod
  def _signals(cls, value: list[str]) -> list[str]:
    known = {name for name, *_ in ALERT_TYPES}
    if not set(value) <= known:
      raise ValueError(f"alert types: {', '.join(sorted(known))}")
    return sorted(set(value))

  @field_validator("coins")
  @classmethod
  def _coins(cls, value: list[str]) -> list[str]:
    value = sorted({coin.strip().upper() for coin in value if coin.strip()})
    if any(not re.fullmatch(r"[A-Z0-9]{1,20}", coin) for coin in value):
      raise ValueError("coins: letters and digits only, e.g. BTC")
    return value


class BookAlerts(BaseModel):  # 0 = off
  max_swing_usd: float = Field(0, ge=0, le=10_000_000)
  min_bets: float = Field(0, ge=0, le=50)
  hours: int = Field(6, ge=1, le=168)  # at most one alert per bot this often


class Change(BaseModel):
  switches: dict[str, bool] = Field(default_factory=dict)
  alerts: Alerts | None = None
  secrets: dict[str, str] = Field(default_factory=dict)  # "" clears one
  push: list[str] | None = None  # alert types sent as phone push (nfiforge's, not btcgate's)
  coins: Literal["full", "bots"] | None = None  # the worker's coin list (nfiforge's, docs/BTCGATE.md D2)
  book_alerts: BookAlerts | None = None  # nfiforge's book (btcgate's own book section stays off)

  @field_validator("push")
  @classmethod
  def _push(cls, value: list[str] | None) -> list[str] | None:
    known = {name for name, *_ in ALERT_TYPES}
    if value is not None and not set(value) <= known:
      raise ValueError(f"push: {', '.join(sorted(known))}")
    return None if value is None else sorted(set(value))

  @field_validator("switches")
  @classmethod
  def _switches(cls, value: dict[str, bool]) -> dict[str, bool]:
    if unknown := set(value) - SWITCHES:
      raise ValueError(f"unknown switch: {', '.join(sorted(unknown))}")
    return value

  @field_validator("secrets")
  @classmethod
  def _secrets(cls, value: dict[str, str]) -> dict[str, str]:
    if unknown := set(value) - set(SECRETS):
      raise ValueError(f"unknown key: {', '.join(sorted(unknown))}")
    value = {key: secret.strip() for key, secret in value.items()}
    if any(len(secret) > 200 or not re.fullmatch(r"[\x21-\x7e]*", secret) for secret in value.values()):
      raise ValueError("keys: up to 200 characters, no spaces")
    return value


def _read(path: Path) -> dict:
  try:
    return json.loads(path.read_text())
  except (OSError, ValueError):
    return {}


def _write(path: Path, data: dict, private: bool = False) -> None:
  tmp_path = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")  # two saves at once can't share one
  with os.fdopen(os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644), "w") as f:
    json.dump(data, f, indent=2)
  os.replace(tmp_path, path)


def view(folder: Path) -> dict:
  # what the page shows: the switches with their values, which keys are set (never the keys), the alert settings
  running = _read(folder / "effective.json")  # what the worker runs with (btcgate defaults + the files)
  file = _read(folder / "btcgate.json")
  secret = _read(folder / "btcgate_secret.json")

  def value(key: str):
    section, name = key.split(".")
    if name in file.get(section, {}):  # saved but maybe not running yet
      return file[section][name]
    return running.get(section, {}).get(name)

  have = {
    item_key: bool(secret.get(section_name, {}).get(field_name))
    for item_key, (section_name, field_name) in SECRETS.items()
  }
  alerts = {**running.get("alerts", {}), **file.get("alerts", {})}
  return {
    "sections": [
      {
        "title": title,
        "items": [
          {"key": item_key, "label": label, "help": help_text, "needs": field_name, "on": value(item_key)}
          for item_key, label, help_text, field_name in items
        ],
      }
      for title, items in SECTIONS
    ],
    "not_yet": [{"key": item_key, "label": label, "why": why} for item_key, label, why in NOT_YET],
    "keys": have,
    "alerts": {item_key: alerts.get(item_key) for item_key in ("enabled", "signals", "coins", "cooldown_min")},
    "push": file.get("push", []),
    "coins": file.get("coins", "full"),
    "book_alerts": BookAlerts(**file.get("book_alerts", {})).model_dump(),
    "alert_types": [
      {"name": field_name, "label": label, "help": help_text} for field_name, label, help_text in ALERT_TYPES
    ],
    "running": bool(running),
  }


def save(folder: Path, change: Change) -> None:
  settings = _read(folder / "btcgate.json")
  for key, enabled in change.switches.items():
    section, name = key.split(".")
    settings.setdefault(section, {})[name] = enabled
  if change.alerts:
    settings.setdefault("alerts", {}).update(change.alerts.model_dump())
  if change.push is not None:
    settings["push"] = change.push
  if change.coins is not None:
    settings["coins"] = change.coins
  if change.book_alerts is not None:
    settings["book_alerts"] = change.book_alerts.model_dump()
  for section, values in OFF.items():
    settings[section] = values
  _write(folder / "btcgate.json", settings)
  if change.secrets:
    secret = _read(folder / "btcgate_secret.json")
    for key, value in change.secrets.items():
      section, name = SECRETS[key]
      secret.setdefault(section, {})[name] = value
    _write(folder / "btcgate_secret.json", secret, private=True)
