# demo freqtrade bot on :18080 with made-up but consistent data: ~300 closed trades over 90 days, open positions with
# adds, per-pair candles with signals. For screenshots and trying the ui. Same data every run (fixed seed), times
# move with the clock. Login freqtrader / s3cret, like scripts/demo_fake_bot.py.
import asyncio
import random
import sys
import time
from pathlib import Path

import uvicorn
from fastapi import Header

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "tests"))
from fake_freqtrade import make_fake  # noqa: E402

PAIRS = {
  "BTC": 96000,
  "ETH": 3400,
  "SOL": 190,
  "XRP": 2.3,
  "DOGE": 0.32,
  "LINK": 21,
  "AVAX": 34,
  "SUI": 3.9,
  "ADA": 0.9,
  "NEAR": 5.5,
  "APT": 9.2,
  "ARB": 0.75,
  "OP": 1.9,
  "INJ": 24,
  "TIA": 6.1,
  "WIF": 2.1,
  "FET": 1.4,
  "RUNE": 4.8,
  "ENA": 0.95,
  "TAO": 480,
}
LONG_TAGS = ["11", "12", "21", "41", "61", "102", "120", "141", "144", "161", "163"]
SHORT_TAGS = ["501", "502", "542", "611", "666"]
WIN_EXITS = ["exit_long_normal_max", "exit_profit_long_grind_1", "exit_long_rapid_rsi", "roi", "exit_long_quick_2"]
WIN_EXITS_SHORT = ["exit_short_normal_max", "exit_profit_short_grind_1", "exit_short_rapid_rsi", "roi"]
LOSS_EXITS = ["exit_long_stoploss_doom", "exit_long_derisk_1", "stop_loss"]
START, LEV, MAX_OPEN, TF = 10000.0, 3.0, 8, 300
rng = random.Random(7)
now = time.time()
now_ms = int(now // TF * TF * 1000)


def sym(base: str) -> str:
  return f"{base}/USDT:USDT"


def walk(base: str, start: float, n: int = 1000) -> list[list]:
  # 5m random walk ending now; fixed per pair
  r = random.Random(base)
  price, rows = start * (1 + r.uniform(-0.04, 0.04)), []
  drift = r.uniform(-0.00004, 0.00006)
  for i in range(n):
    move = r.gauss(drift, 0.0028)
    open_price, close = price, price * (1 + move)
    high = max(open_price, close) * (1 + abs(r.gauss(0, 0.0012)))
    low = min(open_price, close) * (1 - abs(r.gauss(0, 0.0012)))
    rows.append([now_ms - (n - 1 - i) * TF * 1000, open_price, high, low, close, r.uniform(2e5, 9e5) / start])
    price = close
  return rows


CANDLES = {sym(b): walk(b, p) for b, p in PAIRS.items()}


def frame(pair: str) -> tuple[list[str], list[list]]:
  rows, closes = CANDLES[pair], [c[4] for c in CANDLES[pair]]
  ema, k, out = closes[0], 2 / 51, []
  gain = loss = 0.0
  r = random.Random(pair + "sig")
  for i, (ts, o, h, low, c, v) in enumerate(rows):
    ema = c * k + ema * (1 - k)
    if i:
      d = c - closes[i - 1]
      gain, loss = (gain * 13 + max(d, 0)) / 14, (loss * 13 + max(-d, 0)) / 14
    rsi = 100 - 100 / (1 + gain / loss) if loss else 50.0
    long_sig = rsi < 33 and r.random() < 0.25
    short_sig = not long_sig and rsi > 70 and r.random() < 0.2
    tag = (r.choice(LONG_TAGS) + " ") if long_sig else (r.choice(SHORT_TAGS) + " ") if short_sig else None
    out.append([None, o, h, low, c, v, ema, rsi, int(long_sig), int(short_sig), tag, r.random() > 0.05, ts])
  cols = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "ema_50",
    "rsi_14",
    "enter_long",
    "enter_short",
    "enter_tag",
    "protections_long_global",
    "__date_ts",
  ]
  return cols, out


def order(oid, side, tag, amount, price, ts):
  return {
    "order_id": oid,
    "ft_order_side": side,
    "ft_order_tag": tag,
    "filled": amount,
    "amount": amount,
    "cost": amount * price,
    "safe_price": price,
    "order_filled_timestamp": int(ts),
    "status": "closed",
  }


def closed_trades() -> list[dict]:
  trades, t = [], now - 90 * 86400
  tid = 1
  while t < now - 4 * 3600 and len(trades) < 320:
    t += rng.expovariate(1 / (90 * 86400 / 330))
    if t > now - 4 * 3600:
      break
    base = rng.choice(list(PAIRS))
    short = rng.random() < 0.25
    hours = min(rng.lognormvariate(1.6, 1.1), 200)
    win = rng.random() < 0.93
    ratio = rng.uniform(0.006, 0.045) if win else -rng.uniform(0.03, 0.16)
    adds = 0 if win and rng.random() < 0.7 else rng.randint(1, 4)
    stake = round(rng.uniform(140, 320) * (1 + 0.35 * (t - now + 90 * 86400) / (90 * 86400)), 2)
    open_ts, close_ts = t * 1000, min(t + hours * 3600, now - 600) * 1000
    open_rate = PAIRS[base] * rng.uniform(0.85, 1.12)
    entries = [
      order(
        f"o{tid}",
        "sell" if short else "buy",
        rng.choice(SHORT_TAGS if short else LONG_TAGS),
        stake * LEV / open_rate,
        open_rate,
        open_ts,
      )
    ]
    for a in range(adds):
      price = open_rate * (1 + (0.012 if short else -0.012) * (a + 1))
      tag = f"grind_{a % 3 + 1}_entry"
      entries.append(
        order(
          f"o{tid}g{a}",
          entries[0]["ft_order_side"],
          tag,
          stake * 0.4 * LEV / price,
          price,
          open_ts + (close_ts - open_ts) * (a + 1) / (adds + 2),
        )
      )
    amount = sum(o["filled"] for o in entries)
    cost = sum(o["cost"] for o in entries)
    avg = cost / amount
    total_stake = cost / LEV
    close_rate = avg * (1 - ratio / LEV) if short else avg * (1 + ratio / LEV)
    profit = round(total_stake * ratio, 2)
    exit_reason = rng.choice(WIN_EXITS_SHORT if short else WIN_EXITS) if win else rng.choice(LOSS_EXITS)
    exit_order = order(f"x{tid}", "buy" if short else "sell", exit_reason, amount, close_rate, close_ts)
    trades.append(
      {
        "trade_id": tid,
        "pair": sym(base),
        "is_open": False,
        "is_short": short,
        "leverage": LEV,
        "stake_amount": round(total_stake, 2),
        "amount": amount,
        "open_rate": avg,
        "close_rate": close_rate,
        "open_timestamp": int(open_ts),
        "close_timestamp": int(close_ts),
        "enter_tag": entries[0]["ft_order_tag"],
        "exit_reason": exit_reason,
        "close_profit": ratio,
        "close_profit_abs": profit,
        "profit_ratio": ratio,
        "profit_abs": profit,
        "total_profit_abs": profit,
        "total_profit_ratio": ratio,
        "realized_profit": profit,
        "nr_of_successful_entries": len(entries),
        "nr_of_successful_exits": 1,
        "funding_fees": 0.0,
        "quote_currency": "USDT",
        "orders": entries + [exit_order],
      }
    )
    tid += 1
  return trades


def open_trades(first_id: int) -> list[dict]:
  # (coin, short, tag, adds, wanted price move since entry); entry candle is picked to land near that move
  plan = [
    ("SOL", False, "144", 2, 0.021),
    ("ETH", False, "41", 0, 0.006),
    ("SUI", False, "102", 3, -0.018),
    ("INJ", True, "542", 1, 0.012),
    ("LINK", False, "161", 1, 0.009),
    ("TAO", True, "611", 0, -0.007),
  ]
  out = []
  for n, (base, short, tag, adds, want) in enumerate(plan):
    pair, rows = sym(base), CANDLES[sym(base)]
    last, sign = rows[-1][4], -1 if short else 1
    idx = min(
      range(100, 940),
      key=lambda i, rows=rows, last=last, sign=sign, want=want: abs(sign * (last - rows[i][4]) / rows[i][4] - want),
    )
    open_rate, open_ts = rows[idx][4], rows[idx][0]
    stake = rng.uniform(380, 520)
    side = "sell" if short else "buy"
    entries = [order(f"p{n}", side, tag, stake * LEV / open_rate, open_rate, open_ts)]
    for a in range(adds):
      j = idx + (1000 - idx) * (a + 1) // (adds + 2)
      price = rows[j][4]
      entries.append(order(f"p{n}g{a}", side, f"grind_{a + 1}_entry", stake * 0.35 * LEV / price, price, rows[j][0]))
    amount = sum(o["filled"] for o in entries)
    cost = sum(o["cost"] for o in entries)
    avg, current = cost / amount, rows[-1][4]
    ratio = ((avg - current) / avg if short else (current - avg) / avg) * LEV
    total_stake = cost / LEV
    realized = round(rng.uniform(0, 6), 2) if adds else 0.0
    profit = round(total_stake * ratio, 2)
    out.append(
      {
        "trade_id": first_id + n,
        "pair": pair,
        "is_open": True,
        "is_short": short,
        "leverage": LEV,
        "amount": amount,
        "enter_tag": tag,
        "open_rate": avg,
        "current_rate": current,
        "open_timestamp": int(open_ts),
        "stake_amount": round(total_stake, 2),
        "profit_ratio": ratio,
        "profit_abs": profit,
        "total_profit_abs": round(profit + realized, 2),
        "total_profit_ratio": (profit + realized) / total_stake,
        "realized_profit": realized,
        "nr_of_successful_entries": len(entries),
        "nr_of_successful_exits": 0,
        "liquidation_price": avg * (1 + 0.95 / LEV) if short else avg * (1 - 0.95 / LEV),
        "funding_fees": -0.4 * n,
        "stop_loss_abs": None,
        "quote_currency": "USDT",
        "orders": entries,
      }
    )
  return out


CLOSED = closed_trades()
OPEN = open_trades(len(CLOSED) + 1)


def profit_stats() -> dict:
  profits = [t["close_profit_abs"] for t in sorted(CLOSED, key=lambda t: t["close_timestamp"])]
  closed_sum, open_sum = sum(profits), sum(t["profit_abs"] for t in OPEN)
  peak = equity = START
  max_dd = max_dd_abs = 0.0
  for p in profits:
    equity += p
    peak = max(peak, equity)
    if peak - equity > max_dd_abs:
      max_dd_abs, max_dd = peak - equity, (peak - equity) / peak
  wins, losses = [p for p in profits if p > 0], [p for p in profits if p <= 0]
  return {
    "profit_closed_coin": round(closed_sum, 2),
    "profit_all_coin": round(closed_sum + open_sum, 2),
    "closed_trade_count": len(CLOSED),
    "trade_count": len(CLOSED) + len(OPEN),
    "winning_trades": len(wins),
    "losing_trades": len(losses),
    "expectancy": round(closed_sum / len(profits), 2),
    "profit_factor": round(sum(wins) / -sum(losses), 2) if losses else None,
    "current_drawdown": round((peak - equity) / peak, 4),
    "max_drawdown": round(max_dd, 4),
    "max_drawdown_abs": round(max_dd_abs, 2),
  }


def build():
  app = make_fake()
  data = app.state.data
  stats = profit_stats()
  wallet = START + stats["profit_closed_coin"]
  used = sum(t["stake_amount"] for t in OPEN)
  open_pl = sum(t["profit_abs"] for t in OPEN)
  data["/show_config"].update(
    {
      "strategy_version": "v18.0.290",
      "max_open_trades": MAX_OPEN,
      "bot_name": "demo",
      "stake_amount": "unlimited",
      "dry_run": True,
    }
  )
  data["/version"]["version"] = "2026.10"
  data["/status"][:] = OPEN
  data["/balance"].clear()
  data["/balance"].update(
    {
      "total": round(wallet + open_pl, 2),
      "total_bot": round(wallet + open_pl, 2),
      "starting_capital": START,
      "stake": "USDT",
      "currencies": [
        {
          "currency": "USDT",
          "free": round(wallet - used, 2),
          "balance": round(wallet, 2),
          "used": round(used, 2),
          "est_stake": round(wallet, 2),
          "stake": "USDT",
          "is_position": False,
          "position": 0,
          "side": "long",
        }
      ],
    }
  )
  data["/profit"].clear()
  data["/profit"].update(stats)
  data["/whitelist"].update({"whitelist": list(CANDLES), "length": len(CANDLES)})
  data["/locks"].update({"lock_count": 0, "locks": []})
  data["/trades"].update({"trades": CLOSED, "trades_count": len(CLOSED), "total_trades": len(CLOSED)})  # closed only
  data["/trades/open/custom-data"][:] = []

  # live routes: health, logs and candles follow the clock
  dynamic = {"/api/v1/health", "/api/v1/logs", "/api/v1/pair_candles"}
  app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) not in dynamic]

  @app.get("/api/v1/health")
  async def health(authorization: str | None = Header(None)):
    ts = time.time() - 4
    return {"last_process": time.strftime("%Y-%m-%d %H:%M:%S+00:00", time.gmtime(ts)), "last_process_ts": int(ts)}

  @app.get("/api/v1/logs")
  async def logs(limit: int = 500, authorization: str | None = Header(None)):
    t = time.time()
    lines = [
      (t - 240, "freqtrade.worker", "INFO", "Bot heartbeat. PID=1, version='2026.10', state='RUNNING'"),
      (t - 180, "freqtrade.freqtradebot", "INFO", "Exit for ETH/USDT:USDT detected. Reason: exit_long_normal_max"),
      (t - 120, "freqtrade.exchange.exchange", "INFO", "Using cached candle (OHLCV) data for SOL/USDT:USDT"),
      (t - 60, "freqtrade.worker", "INFO", "Bot heartbeat. PID=1, version='2026.10', state='RUNNING'"),
    ]
    stamp = lambda ts: time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))  # noqa: E731
    rows = [[stamp(ts), ts, name, level, msg] for ts, name, level, msg in lines]
    return {"log_count": len(rows), "logs": rows}

  def candles(pair: str, columns: list[str] | None, limit: int) -> dict:
    cols, rows = frame(pair if pair in CANDLES else sym("BTC"))
    want = ["date"] + [c for c in (columns or cols) if c in cols and c != "date"]
    idx = [cols.index(c) for c in want]
    rows = [[row[i] for i in idx] for row in rows][-limit:]
    return {"pair": pair, "timeframe": "5m", "columns": want, "data": rows, "length": len(rows)}

  @app.post("/api/v1/pair_candles")
  async def pair_candles(body: dict, authorization: str | None = Header(None)):
    return candles(body["pair"], body.get("columns"), body.get("limit") or 1000)

  @app.get("/api/v1/pair_candles")
  async def pair_candles_all(pair: str, limit: int = 1000, authorization: str | None = Header(None)):
    return candles(pair, None, limit)

  # ahead of the fake's catch-all POST /api/v1/{action}
  app.router.routes.sort(key=lambda r: getattr(r, "path", None) not in dynamic)

  async def tick():  # a new_candle message every candle, so the Data card shows fresh
    while True:
      await app.state.ws_queue.put({"type": "new_candle", "data": [sym("BTC"), "5m", "futures"]})
      await asyncio.sleep(TF - time.time() % TF + 2)

  async def start_ticker():
    app.state.ticker = asyncio.create_task(tick())

  app.router.on_startup.append(start_ticker)
  return app


if __name__ == "__main__":
  print(f"demo bot: {len(CLOSED)} closed, {len(OPEN)} open, wallet {START + profit_stats()['profit_closed_coin']:.2f}")
  uvicorn.run(build(), host="127.0.0.1", port=18080, log_level="warning")
