# bot health checks for one bot, from what the connector already holds; pure so they're easy to test.
# levels: ok, info (worth knowing), warn (probably fix), bad (fix now)

from __future__ import annotations

import time
from typing import Any

from nfiforge.updates import newer


def _check(key: str, level: str, title: str, detail: str = "") -> dict[str, str]:
  return {"key": key, "level": level, "title": title, "detail": detail}


def checks(state: dict[str, Any], logs_debug: bool, logs_missed: bool, ft_latest: str | None) -> list[dict[str, str]]:
  out: list[dict[str, str]] = []
  config = state.get("config") or {}
  now = time.time()

  # ===========================================================================
  # CONNECTION
  # ===========================================================================
  if not state.get("connected"):
    return [_check("api", "bad", "Bot API not reachable", state.get("error") or "")]
  latency = state.get("latency_ms") or 0
  out.append(
    _check(
      "api", "warn" if latency > 1000 else "ok", f"API answers in {latency:.0f} ms", "slow" if latency > 1000 else ""
    )
  )
  out.append(
    _check("ws", "ok", "Live message stream connected")
    if state.get("ws_connected")
    else _check("ws", "warn", "Live message stream not connected", "fills and exits show up late (polling only)")
  )

  # ===========================================================================
  # RUNNING
  # ===========================================================================
  run_state = config.get("state")
  if run_state and run_state != "running":
    out.append(_check("state", "bad", f"Bot is {run_state}", "no new trades are opened"))
  else:
    out.append(_check("state", "ok", "Bot is running"))
  last = (state.get("health") or {}).get("last_process_ts")
  if last:
    age = now - last
    level = "bad" if age > 600 else "warn" if age > 120 else "ok"
    out.append(_check("loop", level, f"Last bot loop {age:.0f} s ago", "the bot may be stuck" if level != "ok" else ""))

  # ===========================================================================
  # MONEY AND RISK
  # ===========================================================================
  if config.get("dry_run") is False:
    out.append(
      _check("mode", "info", "Real money (dry_run is off)", f"{config.get('exchange')} {config.get('trading_mode')}")
    )
  elif config.get("dry_run"):
    out.append(_check("mode", "ok", "Dry run (paper trading)"))
  futures = config.get("trading_mode") == "futures"
  if futures and config.get("margin_mode") == "cross":
    out.append(
      _check("margin", "warn", "Cross margin", "one bad trade can draw on the whole wallet; isolated limits it")
    )
  elif futures:
    out.append(_check("margin", "ok", f"{(config.get('margin_mode') or '?').capitalize()} margin"))
  wide = (config.get("stoploss") or 0) <= -0.5  # strategy manages exits; a stop that far sits past liquidation
  if config.get("dry_run") is False and futures and not config.get("stoploss_on_exchange"):
    out.append(
      _check(
        "sl_exchange", "info", "Stoploss is not placed on the exchange", "if the bot is down, nothing closes positions"
      )
      if wide
      else _check(
        "sl_exchange",
        "warn",
        "Stoploss is not placed on the exchange",
        f"stoploss {config.get('stoploss')}: if the bot or its connection is down, open positions have no stop",
      )
    )
  if wide:
    out.append(
      _check(
        "stoploss", "info", f"Stoploss {config['stoploss'] * 100:.0f} %", "exits are left to the strategy's own logic"
      )
    )
  if config.get("force_entry_enable"):
    out.append(_check("force", "info", "Force entry is on", "trades can be opened by hand from the API / Telegram"))
  stake, slots = config.get("stake_amount"), config.get("max_open_trades")
  slot_text = f"{slots:g} slots" if isinstance(slots, int | float) and slots > 0 else "unlimited slots"
  if stake == "unlimited" and slots:
    out.append(_check("stake", "ok", f"Stake: wallet split over {slot_text}"))
  elif stake:
    out.append(_check("stake", "ok", f"Stake {stake} {config.get('stake_currency') or ''} × {slot_text}"))
  locks = (state.get("locks") or {}).get("lock_count") or 0
  if locks:
    out.append(_check("locks", "info", f"{locks} pair lock{'s' if locks > 1 else ''} active", "see Pairs"))

  # ===========================================================================
  # HOUSEKEEPING
  # ===========================================================================
  if logs_debug or logs_missed:
    out.append(
      _check(
        "debug",
        "warn",
        "Bot logs at debug level (-v)",
        "more cpu and disk; freqtrade's api keeps 1000 lines, so the Logs page misses lines. Run without -v",
      )
    )
  version = state.get("version")
  if version and ft_latest and newer(ft_latest, version):
    out.append(_check("ft_version", "info", f"freqtrade {ft_latest} is out", f"this bot runs {version}"))
  elif version:
    out.append(_check("ft_version", "ok", f"freqtrade {version}", "latest" if ft_latest else ""))
  return out
