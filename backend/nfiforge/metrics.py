# small numeric helpers, no pandas needed

from __future__ import annotations

import math


def rsi(closes: list[float], period: int = 14) -> float | None:
  # wilder rsi on the last value
  if len(closes) <= period:
    return None
  gains = losses = 0.0
  for previous, current in zip(closes[:period], closes[1 : period + 1], strict=False):
    change = current - previous
    gains += max(change, 0)
    losses += max(-change, 0)
  avg_gain, avg_loss = gains / period, losses / period
  for previous, current in zip(closes[period:-1], closes[period + 1 :], strict=False):
    change = current - previous
    avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
    avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
  return 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)


def resample_closes(rows: list[list[float]], seconds: int) -> list[float]:
  # rows = [[ts, close], ...] in time order -> last close of each bucket
  out: dict[int, float] = {}
  for timestamp, close in rows:
    out[int(timestamp // seconds)] = close
  return [out[bucket] for bucket in sorted(out)]


def pct_change(closes: list[float], back: int) -> float | None:
  if len(closes) <= back or not closes[-1 - back]:
    return None
  return (closes[-1] / closes[-1 - back] - 1) * 100


def wilson(wins: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
  # 95 % interval for a win rate
  if total == 0:
    return None
  rate = wins / total
  den = 1 + z * z / total
  mid = (rate + z * z / (2 * total)) / den
  half = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / den
  return max(0.0, mid - half), min(1.0, mid + half)
