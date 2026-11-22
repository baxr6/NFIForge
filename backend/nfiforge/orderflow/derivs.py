# open interest, funding and liquidations of a perpetual, from what each exchange offers through ccxt. amounts in base
# units (ccxt gives contracts). checked 22/10/2026: oi history pages forward from `since` on bybit / binance / okx /
# gate, kucoin answers the latest page only, htx keeps 1h and up; bitget / hyperliquid only the current oi, mexc none.
# liquidations: a stream on binance / bybit / okx (binance sends at most one per pair per second), a public list on
# gate / htx, nothing elsewhere

from __future__ import annotations

import ccxt.pro as ccxtpro

OI_TF = ("5m", "1h")  # history period: the first one the exchange takes
PAGES = 40  # oi history pages per round

# the ccxt liquidation side that means a LONG was liquidated: bybit and gate report the position, the others the
# liquidation order (a sell closes a long)
LONG_SIDE = {"bybit": "buy", "gate": "buy"}


def long_liquidated(exchange_id: str, side: str | None) -> bool:
  return (side or "").lower() == LONG_SIDE.get(exchange_id, "sell")


def can(exchange, what: str) -> bool:
  return bool(exchange.has.get(what))  # True or "emulated"


async def oi_history(exchange, symbol: str, since: int, contract: float) -> list[tuple[int, float]]:
  # (ms, base amount) from `since`, oldest first; [] when the exchange keeps no history
  if not can(exchange, "fetchOpenInterestHistory"):
    return []
  for timeframe in OI_TF:
    out: list[tuple[int, float]] = []
    cursor = since
    try:
      for _ in range(PAGES):
        rows = await exchange.fetch_open_interest_history(symbol, timeframe, since=cursor, limit=200)
        rows = [
          row for row in rows if row.get("timestamp") and row["timestamp"] >= cursor and row.get("openInterestAmount")
        ]
        if not rows:
          break
        out += [(int(row["timestamp"]), float(row["openInterestAmount"]) * contract) for row in rows]
        cursor = int(rows[-1]["timestamp"]) + 1
      return out
    except ccxtpro.BadRequest:  # period not offered: try the next
      continue
  return []


async def oi_now(exchange, symbol: str, contract: float) -> tuple[int, float] | None:
  if not can(exchange, "fetchOpenInterest"):
    return None
  interest = await exchange.fetch_open_interest(symbol)
  amount = interest.get("openInterestAmount")
  if amount is None:
    return None
  return int(interest.get("timestamp") or exchange.milliseconds()), float(amount) * contract


async def funding_history(exchange, symbol: str, since: int) -> list[tuple[int, float]]:
  # settled funding rates (ms, rate per period) from `since`
  if not can(exchange, "fetchFundingRateHistory"):
    return []
  out: list[tuple[int, float]] = []
  cursor = since
  for _ in range(10):
    rows = await exchange.fetch_funding_rate_history(symbol, since=cursor, limit=200)
    rows = [
      row for row in rows if row.get("timestamp") and row["timestamp"] >= cursor and row.get("fundingRate") is not None
    ]
    if not rows:
      break
    out += [(int(row["timestamp"]), float(row["fundingRate"])) for row in rows]
    cursor = int(rows[-1]["timestamp"]) + 1
  return out


async def funding_now(exchange, symbol: str) -> dict | None:
  # the rate the next settlement will use (as it stands) and when it settles
  if not can(exchange, "fetchFundingRate"):
    return None
  funding = await exchange.fetch_funding_rate(symbol)
  if funding.get("fundingRate") is None:
    return None
  return {
    "rate": float(funding["fundingRate"]),
    "next": funding.get("fundingTimestamp") or funding.get("nextFundingTimestamp"),
  }


def liq_rows(exchange_id: str, liqs: list[dict], contract: float) -> list[tuple[int, float, float, int]]:
  # ccxt liquidations -> (ms, price, base amount, 1 = a long was liquidated)
  out = []
  for liq in liqs:
    price, contracts = liq.get("price"), liq.get("contracts")
    if not liq.get("timestamp") or not price or not contracts:
      continue
    out.append(
      (
        int(liq["timestamp"]),
        float(price),
        float(contracts) * contract,
        int(long_liquidated(exchange_id, liq.get("side"))),
      )
    )
  return out
