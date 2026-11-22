# best and worst move of every closed trade (MFE / MAE) from exchange candles over its life. measured once each in the
# background, about two a second, kept in the store; the Analytics scatter reads them

from __future__ import annotations

import asyncio
import logging
from typing import Any

import ccxt.async_support as ccxt

from nfiforge.connectors.market import CandleSource
from nfiforge.store import Store

log = logging.getLogger(__name__)


# every candle the trade was open in (the one it opened in too, so a trade inside one candle still counts), against the
# average entry
def measure(trade: dict[str, Any], candles: list[list], seconds: int) -> tuple[float, float] | None:
  start, end = trade["open_timestamp"] / 1000, trade["close_timestamp"] / 1000
  life = [
    candle
    for candle in candles
    if start - seconds < candle[0] / 1000 <= end and candle[2] is not None and candle[3] is not None
  ]
  if not life or not trade.get("open_rate"):
    return None
  high, low = max(candle[2] for candle in life), min(candle[3] for candle in life)
  rise, fall = (high / trade["open_rate"] - 1) * 100, (low / trade["open_rate"] - 1) * 100
  return (-fall, -rise) if trade.get("is_short") else (rise, fall)


class Excursions:
  def __init__(self, store: Store, market: CandleSource, bots: dict[str, Any]) -> None:
    self.store, self.market, self.bots = store, market, bots

  async def run(self, every: float = 60, pause: float = 0.5) -> None:
    await asyncio.sleep(20)  # let the bots load their history first
    while True:
      for name in list(self.bots):
        try:
          await self._bot(name, pause)
        except Exception:
          log.exception("%s: trade excursions failed", name)
      await asyncio.sleep(every)

  async def _bot(self, name: str, pause: float) -> None:
    connector = self.bots.get(name)
    config = (connector.state["config"] or {}) if connector else {}
    if not config.get("exchange"):
      return
    futures = config.get("trading_mode") == "futures"
    done = await asyncio.to_thread(self.store.excursions, name)
    todo = [
      trade
      for trade in connector.history.values()
      if (trade["trade_id"], trade.get("open_timestamp")) not in done
      and not trade.get("is_open")
      and trade.get("open_timestamp")
      and trade.get("close_timestamp")
    ]
    for trade in sorted(todo, key=lambda trade: trade["close_timestamp"], reverse=True):  # newest first
      if self.bots.get(name) is not connector:
        return  # bot removed or edited meanwhile
      try:
        timeframe, seconds, candles = await self.market.trade_candles(
          config["exchange"], futures, trade["pair"], trade["open_timestamp"] / 1000, trade["close_timestamp"] / 1000
        )
        excursion = measure(trade, candles, seconds)
        row = (*excursion, timeframe, None) if excursion else (None, None, timeframe, "no candles for the trade's time")
      except ccxt.BadSymbol:
        row = (None, None, None, "pair not on the exchange any more")
      except Exception as e:
        log.info("%s: excursion of trade %s failed (%s), next round", name, trade["trade_id"], e)
        return  # exchange or network trouble: try again next round
      await asyncio.to_thread(self.store.add_excursion, name, trade["trade_id"], trade["open_timestamp"], *row)
      await asyncio.sleep(pause)
