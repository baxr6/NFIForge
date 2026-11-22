# signal radar: every whitelisted pair's entry signals and the strategy's guard columns per candle, kept for 7 days
# (saved, so a restart keeps them), and what happened to each signal (traded, or why not). one small request per pair
# after each new candle

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
  from nfiforge.store import Store

# nfi's guard columns (permit conditions: false = blocking); other strategies just don't have them
GUARDS = (
  "protections_long_global",
  "protections_short_global",
  "global_protections_long_pump",
  "global_protections_long_dump",
  "global_protections_short_pump",
  "global_protections_short_dump",
)
COLUMNS = ["__date_ts", "enter_long", "enter_short", "enter_tag", *GUARDS]
CANCEL = re.compile(r"Cancelling entry for (\S+) due to (.+?)\.?$")
# freqtrade's own refusals: "Unable to create trade for X: Available balance (..) is lower than stake amount (..)"
UNABLE = re.compile(r"Unable to create trade for (\S+): (.+?)\.?$")
# an entry order that never filled (the trade is then deleted, so it isn't in the trade list): a long's buy or a
# short's sell, "Buy order cancelled due to timeout for Trade(id=5, pair=X, amount=.., is_short=False, .."
UNFILLED = re.compile(
  r"(Buy|Sell) order (?:fully )?cancell?ed(?: due to (.+?))? for Trade\(id=\d+, pair=([^,]+),.*?is_short=(True|False)"
)
KEEP_S = 7 * 86400
TF_S = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def tf_seconds(timeframe: str) -> int:
  return TF_S.get(timeframe, 300)


class Radar:
  def __init__(self, store: Store | None = None, bot: str = "") -> None:
    self.store, self.bot = store, bot
    # pair -> candle open (s) -> (long, short, tag, guards off bitmask); only candles with a signal or a guard off
    self.rows: dict[str, dict[float, tuple[bool, bool, str, int]]] = {}
    self.latest: dict[str, tuple[float, int]] = {}  # pair -> (newest candle, guards off on it), quiet ones too
    self.reasons: list[list] = []  # the log lines that explain a signal, kept as long as the signals
    self.swept: float | None = None
    self.resume: float | None = None  # the last sweep before a restart, so the first one only fills the gap
    if store:
      since = time.time() - KEEP_S
      for pair, timestamp, long, short, tag, off in store.radar_rows(bot, since):
        self.rows.setdefault(pair, {})[timestamp] = (long, short, tag, off)
      self.reasons = [["", timestamp, "", "", message] for timestamp, message in store.radar_logs(bot, since)]
      self.resume = store.radar_swept(bot)

  # ---------------------------------------------------------------------------
  # COLLECT
  # ---------------------------------------------------------------------------
  def add(self, pair: str, frame: dict[str, Any]) -> None:
    cols = frame.get("columns") or []
    keep = self.rows.setdefault(pair, {})
    new = []
    for values in frame.get("data") or []:
      row = dict(zip(cols, values, strict=False))
      timestamp = row.get("__date_ts")
      if timestamp is None:
        continue
      timestamp = timestamp / 1000 if timestamp > 1e11 else timestamp
      off = sum(1 << i for i, guard in enumerate(GUARDS) if guard in row and row[guard] is not None and not row[guard])
      tag = str(row.get("enter_tag") or "").strip()
      cell = (bool(row.get("enter_long")), bool(row.get("enter_short")), tag, off)
      if timestamp >= self.latest.get(pair, (0, 0))[0]:
        self.latest[pair] = (timestamp, off)
      if (cell[0] or cell[1] or off) and keep.get(timestamp) != cell:
        keep[timestamp] = cell
        new.append((pair, timestamp, *cell))
    if self.store:
      self.store.add_radar(self.bot, new)

  def log(self, line: list) -> None:
    # every new bot log line passes here; the ones a signal's outcome can come from are kept
    msg = line[4]
    if CANCEL.search(msg) or UNABLE.search(msg) or UNFILLED.search(msg):
      self.reasons.append(line)
      if self.store:
        self.store.add_radar_log(self.bot, line[1], msg)

  def prune(self, whitelist: list[str], now: float) -> None:
    cut = now - KEEP_S
    for pair in list(self.rows):
      self.rows[pair] = {timestamp: value for timestamp, value in self.rows[pair].items() if timestamp >= cut}
      if not self.rows[pair] and pair not in whitelist:
        del self.rows[pair]
    for pair in list(self.latest):
      if pair not in whitelist and pair not in self.rows:
        del self.latest[pair]
    self.reasons = [reason for reason in self.reasons if reason[1] >= cut]
    self.swept = now
    if self.store:
      self.store.set_radar_swept(self.bot, now, cut)

  # ---------------------------------------------------------------------------
  # VIEW: only candles with a signal or a guard off; quiet candles are implied
  # ---------------------------------------------------------------------------
  def view(
    self,
    state: dict[str, Any],
    trades: list[dict[str, Any]],
    logs: list[list],
    now: float | None = None,
    since: float = 0,
  ) -> dict:
    now = now or time.time()
    logs = [*self.reasons, *logs]
    timeframe = (state.get("config") or {}).get("timeframe") or "5m"
    seconds = tf_seconds(timeframe)
    # freqtrade sends 8.0, not 8
    max_open = (state.get("config") or {}).get("max_open_trades")
    max_open = int(max_open) if isinstance(max_open, int | float) and max_open > 0 else None
    spans = [
      (
        trade["pair"],
        bool(trade.get("is_short")),
        trade["open_timestamp"] / 1000,
        (trade.get("close_timestamp") or 0) / 1000 or 1e18,
      )
      for trade in trades
      if trade.get("open_timestamp")
    ]
    by_pair: dict[str, list] = {}
    for span in spans:
      by_pair.setdefault(span[0], []).append(span)
    locks = [
      (lock.get("pair"), (lock.get("lock_timestamp") or 0) / 1000, (lock.get("lock_end_timestamp") or 0) / 1000)
      for lock in (state.get("locks") or {}).get("locks") or []
    ]
    cancels: dict[str, list[tuple[float, str]]] = {}
    unable: dict[str, list[tuple[float, str]]] = {}
    unfilled: dict[tuple[str, bool], list[tuple[float, str]]] = {}
    for _, timestamp, _, _, msg in logs:
      if match := CANCEL.search(msg):
        cancels.setdefault(match[1], []).append((timestamp, match[2]))
      elif match := UNABLE.search(msg):
        unable.setdefault(match[1], []).append((timestamp, match[2]))
      elif (match := UNFILLED.search(msg)) and (match[1] == "Buy") == (match[4] == "False"):
        unfilled.setdefault((match[3], match[4] == "True"), []).append((timestamp, match[2] or "cancelled"))

    def outcome(pair: str, signal_at: float, short: bool) -> tuple[str, str]:
      decide = signal_at + seconds  # the signal candle closes, the bot acts
      if decide > now - 60:
        return "pending", "the bot may still act on this candle"
      for _, is_short, opened, _ in by_pair.get(pair, []):
        if is_short == short and decide - 60 <= opened <= decide + seconds + 60:
          return "traded", ""
      for _, _, opened, closed in by_pair.get(pair, []):
        if opened < decide - 60 and closed > decide:
          return "blocked", "already in a trade on this pair"
      for timestamp, why in cancels.get(pair, []):
        if decide - 60 <= timestamp <= decide + seconds + 120:
          return "blocked", f"strategy: {why}"
      for timestamp, why in unable.get(pair, []):
        if decide - 60 <= timestamp <= decide + seconds + 120:
          return "blocked", f"freqtrade: {why}"
      # placed when the candle closed, cancelled when the unfilled timeout ran out (within 2 h)
      for timestamp, why in unfilled.get((pair, short), []):
        if decide - 60 <= timestamp <= decide + 7200:
          return "blocked", f"entry order not filled ({why})"
      for lock_pair, lock_start, lock_end in locks:
        if lock_pair in (pair, "*") and lock_start <= decide <= lock_end:
          return "blocked", "pair locked"
      if max_open and sum(1 for _, _, opened, closed in spans if opened <= decide < closed) >= max_open:
        return "blocked", f"all {max_open} slots full"
      return "not taken", "no reason found in trades, locks or logs (strategy check or exchange)"

    # cell = [candle, side, tag, outcome, reason, guards off, candles]; a run of guard-only candles with the same
    # guards off is one cell, so a guard that stays off for days stays small
    pairs: dict[str, list] = {}
    for pair, rows in self.rows.items():
      cells: list[list] = []
      for trade in sorted(rows):
        if trade < since:
          continue
        long, short, tag, off = rows[trade]
        if long or short:
          side = "S" if short and not long else "L"
          what, why = outcome(pair, trade, side == "S")
          cells.append([trade, side, tag, what, why, off, 1])
        elif cells and not cells[-1][1] and cells[-1][5] == off and trade == cells[-1][0] + cells[-1][6] * seconds:
          cells[-1][6] += 1
        else:
          cells.append([trade, "", "", "", "", off, 1])
      if cells:
        pairs[pair] = cells
    summary = {guard: sum(1 for _, mask in self.latest.values() if mask & (1 << i)) for i, guard in enumerate(GUARDS)}
    return {
      "enabled": True,
      "timeframe": timeframe,
      "seconds": seconds,
      "swept": self.swept,
      "guards": list(GUARDS),
      "pairs_watched": len(self.latest),
      "summary": summary,
      "pairs": pairs,
    }
