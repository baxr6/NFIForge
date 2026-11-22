# ===========================================================================
# FIAT: what a usdt amount is worth in a real currency, from a real usdt market (usdt isn't exactly 1 usd).
# display only; the bots keep trading in usdt. public prices, no keys
# ===========================================================================
from __future__ import annotations

import asyncio
import logging
import time

import httpx

log = logging.getLogger(__name__)

# kraken has a direct usdt market for each of these; anything else would need a second rate, so less exact
CURRENCIES = ("AUD", "USD", "EUR", "GBP", "CAD", "CHF", "JPY")
FRESH_S = 60  # ask again after this
STALE_S = 300  # older than this and no rate is shown


async def _kraken(client: httpx.AsyncClient, currency: str) -> float:
  response = (await client.get("https://api.kraken.com/0/public/Ticker", params={"pair": f"USDT{currency}"})).json()
  if response.get("error"):
    raise ValueError(response["error"])
  ticker = next(iter(response["result"].values()))
  return (float(ticker["a"][0]) + float(ticker["b"][0])) / 2


async def _btcmarkets(client: httpx.AsyncClient, currency: str) -> float:
  response = (await client.get(f"https://api.btcmarkets.net/v3/markets/USDT-{currency}/ticker")).json()
  return (float(response["bestBid"]) + float(response["bestAsk"])) / 2


# kraken first; btc markets (australian) as a fallback for aud
SOURCES = {currency: [("kraken", _kraken)] for currency in CURRENCIES}
SOURCES["AUD"].append(("btcmarkets", _btcmarkets))


class Fx:
  def __init__(self) -> None:
    self._rates: dict[str, dict] = {}
    self._lock = asyncio.Lock()

  async def rate(self, currency: str) -> dict | None:
    # {currency, rate, ts, source}, or None when no source has given a rate in the last 5 minutes
    currency = currency.upper()
    if currency not in SOURCES:
      raise ValueError(f"no usdt market for {currency}")
    async with self._lock:
      have = self._rates.get(currency)
      if have is None or time.time() - have["ts"] > FRESH_S:
        async with httpx.AsyncClient(timeout=5) as client:
          for name, fetch in SOURCES[currency]:
            try:
              rate = await fetch(client, currency)
            except Exception as e:
              log.warning("usdt/%s from %s failed: %s", currency, name, type(e).__name__)
              continue
            if rate > 0:
              have = self._rates[currency] = {"currency": currency, "rate": rate, "ts": time.time(), "source": name}
              break
    return have if have and time.time() - have["ts"] <= STALE_S else None
