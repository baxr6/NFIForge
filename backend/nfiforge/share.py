# results without amounts, for share links and percent-only viewers (docs/SHARING.md). every number here is a
# percentage, a count, a ratio or a time: the answer is built key by key from the bot's state, never by removing
# keys from it, so nothing that gives away the account size (balance, stake, amounts, prices, profit in coin) can
# slip through when freqtrade or NFIForge adds a field

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

OPTS = ("positions", "trades", "tags", "names")  # what a share link shows besides the summary; all on for viewers
TRADES = 50
DAYS = 365


def clean(body: Any, bot_names: list[str]) -> dict:
  # a new share link's settings from the admin; ValueError says what's wrong
  if not isinstance(body, dict):
    raise ValueError("send name, bots, days and the switches")
  name = str(body.get("name") or "").strip()
  if not 1 <= len(name) <= 60:
    raise ValueError("name: 1-60 characters")
  bots = body.get("bots")
  if not (isinstance(bots, list) and bots and all(bot in bot_names for bot in bots)):
    raise ValueError("bots: one or more of your bots")
  days = body.get("days")
  if days is not None and not (isinstance(days, int) and 1 <= days <= 3650):
    raise ValueError("days: 1-3650, or none for no expiry")
  options = {key: bool(body.get(key)) for key in OPTS}
  return {"name": name, "bots": sorted(set(bots), key=bots.index), "days": days, "opts": options}


def _num(value: Any) -> float:
  try:
    return float(value or 0)
  except (TypeError, ValueError):
    return 0.0


def _pct(value: float) -> float:
  return round(value, 3)


def _day(timestamp_ms: float) -> str:
  return datetime.fromtimestamp(timestamp_ms / 1000, UTC).strftime("%Y-%m-%d")


def bot_view(state: dict, history: list[dict], label: str, options: dict, now: float | None = None) -> dict:
  # one bot, in percent of its account (starting capital plus what it closed before)
  now = now or time.time()
  cap = _num((state.get("balance") or {}).get("starting_capital"))
  closed = sorted(
    (trade for trade in history if trade.get("close_timestamp")), key=lambda trade: trade["close_timestamp"]
  )
  pnl = [_num(trade.get("close_profit_abs")) for trade in closed]

  # realised equity as an index from 100, its deepest fall, and profit % per window / day
  index, run, peak, deepest = [], 0.0, 0.0, 0.0
  if cap > 0 and closed:
    index.append([closed[0].get("open_timestamp") or closed[0]["close_timestamp"], 100.0])
  for trade, profit in zip(closed, pnl, strict=True):
    run += profit
    if cap > 0:
      index.append([trade["close_timestamp"], _pct((cap + run) / cap * 100)])
      peak = max(peak, run)
      deepest = min(deepest, (run - peak) / (cap + peak) * 100)

  def since(timestamp_ms: float) -> float | None:
    before = sum(profit for trade, profit in zip(closed, pnl, strict=True) if trade["close_timestamp"] < timestamp_ms)
    after = sum(profit for trade, profit in zip(closed, pnl, strict=True) if trade["close_timestamp"] >= timestamp_ms)
    return _pct(after / (cap + before) * 100) if cap > 0 and cap + before > 0 else None

  today = (now - now % 86400) * 1000
  daily: dict[str, list[float]] = {}  # day -> [profit, account at its start, trades]
  run = 0.0
  for trade, profit in zip(closed, pnl, strict=True):
    day = daily.setdefault(_day(trade["close_timestamp"]), [0.0, cap + run, 0])
    day[0] += profit
    day[2] += 1
    run += profit
  first_day = _day((now - DAYS * 86400) * 1000)
  days = [
    {"day": day_key, "pct": _pct(totals[0] / totals[1] * 100), "trades": int(totals[2])}
    for day_key, totals in daily.items()
    if day_key >= first_day and cap > 0 and totals[1] > 0
  ]

  wins = [profit for profit in pnl if profit > 0]
  gross_win, gross_loss = sum(wins), -sum(profit for profit in pnl if profit < 0)
  status = state.get("status") or []
  config = state.get("config") or {}
  wallet = cap + sum(pnl)
  open_now = sum(_num(trade.get("profit_abs")) for trade in status)
  out: dict[str, Any] = {
    "name": label,
    "connected": bool(state.get("connected")),
    "exchange": config.get("exchange") if options["names"] else None,
    "summary": {
      "today": since(today),
      "week": since(today - 6 * 86400000),
      "month": since(today - 29 * 86400000),
      "all": _pct(sum(pnl) / cap * 100) if cap > 0 else None,
      "open": _pct(open_now / wallet * 100) if cap > 0 and wallet > 0 else None,
      "trades": len(closed),
      "won": _pct(len(wins) / len(closed) * 100) if closed else None,
      "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
      "drawdown": _pct(deepest),
      "slots": len(status),
      "slots_max": int(config["max_open_trades"]) if isinstance(config.get("max_open_trades"), int | float) else None,
    },
    "equity": index[-1000:] if len(index) <= 1000 else index[:: len(index) // 1000 + 1] + [index[-1]],
    "daily": days,
  }
  if options["positions"]:
    out["open"] = [
      {
        "pair": trade.get("pair"),
        "short": bool(trade.get("is_short")),
        "leverage": _num(trade.get("leverage")) or 1,
        "opened": trade.get("open_timestamp"),
        "pct": _pct(_num(trade.get("total_profit_ratio", trade.get("profit_ratio"))) * 100),
        "entries": int(_num(trade.get("nr_of_successful_entries")) or 1),
      }
      | ({"tag": (trade.get("enter_tag") or "").strip()} if options["tags"] else {})
      for trade in status
    ]
  if options["trades"]:
    out["closed"] = [
      {
        "pair": trade.get("pair"),
        "short": bool(trade.get("is_short")),
        "leverage": _num(trade.get("leverage")) or 1,
        "opened": trade.get("open_timestamp"),
        "closed": trade["close_timestamp"],
        "pct": _pct(_num(trade.get("close_profit")) * 100),
      }
      | ({"tag": (trade.get("enter_tag") or "").strip(), "exit": trade.get("exit_reason")} if options["tags"] else {})
      for trade in reversed(closed[-TRADES:])
    ]
  return out


def view(bots: dict[str, Any], names: list[str], options: dict, title: str = "") -> dict:
  # the page: the listed bots that still exist, in that order. bots: name -> connector (state + history)
  shown = [name for name in names if name in bots]
  return {
    "title": title,
    "opts": options,
    "ts": int(time.time() * 1000),
    "bots": [
      bot_view(bots[name].state, list(bots[name].history.values()), name if options["names"] else f"Bot {i}", options)
      for i, name in enumerate(shown, 1)
    ],
  }


def row(record: tuple) -> dict:
  # a stored share link, as the admin's list shows it (never the code: only its hash is kept)
  share_id, _code, name, bots, options, created, expires, last_seen, opens = record
  return {
    "id": share_id,
    "name": name,
    "bots": json.loads(bots),
    "opts": json.loads(options),
    "created": created,
    "expires": expires,
    "last_seen": last_seen,
    "opens": opens,
  }
