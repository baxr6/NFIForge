# fake freqtrade api_server: login, the endpoints nfiforge polls, message websocket

from __future__ import annotations

import asyncio
import base64
import secrets
import time

from fastapi import Body, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect

USER, PASSWORD = "freqtrader", "s3cret"
STRATEGY = "NostalgiaForInfinityX8"


def make_fake(strategy: str = STRATEGY) -> FastAPI:
  app = FastAPI()
  tokens: set[str] = set()
  app.state.ws_queue = asyncio.Queue()

  def _check_basic(auth: str | None) -> None:
    if not auth or not auth.startswith("Basic "):
      raise HTTPException(401)
    user, _, password = base64.b64decode(auth[6:]).decode().partition(":")
    if (user, password) != (USER, PASSWORD):
      raise HTTPException(401)

  def _check_bearer(auth: str | None) -> None:
    if not auth or auth.removeprefix("Bearer ") not in tokens:
      raise HTTPException(401)

  @app.post("/api/v1/token/login")
  async def login(authorization: str | None = Header(None)):
    _check_basic(authorization)
    access, refresh_token = secrets.token_hex(8), secrets.token_hex(8)
    tokens.update({access, refresh_token})
    return {"access_token": access, "refresh_token": refresh_token}

  @app.post("/api/v1/token/refresh")
  async def refresh(authorization: str | None = Header(None)):
    _check_bearer(authorization)
    access = secrets.token_hex(8)
    tokens.add(access)
    return {"access_token": access}

  data = {
    "/show_config": {
      "strategy": strategy,
      "strategy_version": "v18.0.119",
      "exchange": "bybit",
      "trading_mode": "futures",
      "dry_run": True,
      "stake_currency": "USDT",
      "max_open_trades": 8,
      "timeframe": "5m",
      "state": "running",
      "bot_name": "fake",
    },
    "/version": {"version": "2026.9"},
    "/blacklist": {
      "blacklist": ["(LAVA)/.*"],
      "blacklist_expanded": ["LAVA/USDT:USDT"],
      "method": ["VolumePairList", "AgeFilter"],
      "length": 1,
    },
    "/locks": {"lock_count": 1, "locks": [{"id": 1, "pair": "ETH/USDT:USDT", "side": "*", "reason": "cooldown"}]},
    "/status": [
      {
        "trade_id": 1,
        "pair": "APE/USDT:USDT",
        "is_open": True,
        "amount": 12000.0,
        "is_short": False,
        "leverage": 3.0,
        "enter_tag": "144",
        "profit_ratio": -0.0291,
        "profit_abs": -57.94,
        "open_rate": 0.1661,
        "current_rate": 0.16449,
        "open_timestamp": 1791158400000 - 2 * 86400000,
        "nr_of_successful_entries": 3,
        "realized_profit": 1.39,
        "total_profit_abs": -56.55,
        "total_profit_ratio": -0.0284,
        "quote_currency": "USDT",
        "stake_amount": 1991.0,
        "liquidation_price": 0.1159,
        "orders": [
          {
            "order_id": "a",
            "ft_order_side": "buy",
            "ft_order_tag": "144",
            "filled": 4000,
            "cost": 664.4,
            "safe_price": 0.1661,
            "order_filled_timestamp": 1791158400000 - 2 * 86400000,
          },
          {
            "order_id": "b",
            "ft_order_side": "buy",
            "ft_order_tag": "grind_1_entry",
            "filled": 4200,
            "cost": 663.0,
            "safe_price": 0.1579,
            "order_filled_timestamp": 1791158400000 - 86400000,
          },
          {
            "order_id": "c",
            "ft_order_side": "buy",
            "ft_order_tag": "grind_2_entry",
            "filled": 4100,
            "cost": 663.6,
            "safe_price": 0.1619,
            "order_filled_timestamp": 1791158400000 - 30 * 3600000,
          },
        ],
      }
    ],
    "/health": {"last_process": "2026-10-05 00:00:00+00:00", "last_process_ts": 1791158400},
    "/balance": {"total": 10399.68, "starting_capital": 9552.66, "stake": "USDT", "currencies": []},
    "/profit": {
      "profit_closed_coin": 901.33,
      "profit_all_coin": 843.39,
      "closed_trade_count": 19,
      "trade_count": 20,
      "winning_trades": 19,
      "losing_trades": 0,
      "expectancy": 47.44,
      "profit_factor": None,
      "current_drawdown": 0.018,
      "max_drawdown": 0.106,
      "max_drawdown_abs": 1102.0,
    },
    "/whitelist": {"whitelist": ["BTC/USDT:USDT", "ETH/USDT:USDT"], "length": 2, "method": ["VolumePairList"]},
    "/trades": {
      "trades": [
        {
          "trade_id": 9,
          "pair": "ETH/USDT:USDT",
          "is_open": False,
          "is_short": False,
          "leverage": 3.0,
          "stake_amount": 200.0,
          "open_rate": 2400.0,
          "close_rate": 2416.8,
          "close_profit": 0.021,
          "open_timestamp": 1791150000000 - 3 * 3600000,
          "orders": [
            {
              "order_id": "e1",
              "ft_order_side": "buy",
              "ft_order_tag": "141",
              "filled": 0.25,
              "cost": 600.0,
              "safe_price": 2400.0,
              "order_filled_timestamp": 1791150000000 - 3 * 3600000,
            },
            {
              "order_id": "x1",
              "ft_order_side": "sell",
              "ft_order_tag": "roi",
              "filled": 0.25,
              "cost": 604.2,
              "safe_price": 2416.8,
              "order_filled_timestamp": 1791150000000,
            },
          ],
          "close_profit_abs": 4.2,
          "close_timestamp": 1791150000000,
          "exit_reason": "roi",
          "enter_tag": "141",
        }
      ],
      "trades_count": 1,
      "total_trades": 1,
      "offset": 0,
    },
    "/logs": {
      "log_count": 4,
      "logs": [
        [
          "2026-10-05 03:00:00",
          1791162000.0,
          "freqtrade.worker",
          "INFO",
          "GET /api/v1/message/ws?token=eyJabc.def [accepted]",
        ],
        ["2026-10-05 03:00:01", 1791162001.0, "freqtrade.freqtradebot", "INFO", "Exit for ETH/USDT:USDT detected."],
        ["2026-10-05 03:00:02", 1791162002.0, "freqtrade.exchange.common", "WARNING", "candle history failed"],
        [
          "2026-10-05 03:00:03",
          1791162003.0,
          "AgeFilter",
          "INFO",
          "Removed ETH/USDT:USDT from whitelist, because age 3 is less than 10 days",
        ],
      ],
    },
    "/trades/open/custom-data": [
      {"trade_id": 1, "custom_data": [{"key": "grind_1_cluster_max_profit_rate", "value": 0.012}]}
    ],
  }

  now_ms = int(time.time() // 300 * 300 * 1000)  # candles end now (the radar keeps only the last 24 h)
  candles = [[now_ms - (999 - i) * 300000, 60000 + i, 60010 + i, 59990 + i, 60005 + i, 10.0] for i in range(1000)]

  # full frame: ohlcv plus two strategy columns, like a real analysed dataframe
  # plus a strategy's signal and guard columns: a long signal (tag 144) 9 candles back, nfi's long guard off on the last
  signal_cols = ["enter_long", "enter_short", "enter_tag", "protections_long_global"]
  all_cols = ["date", "open", "high", "low", "close", "volume", "ema_50", "rsi_14", *signal_cols, "__date_ts"]
  frame = [
    [
      None,
      open_price,
      high,
      low,
      close,
      volume,
      close - 5,
      55.0,
      int(i == 990),
      0,
      "144 " if i == 990 else None,
      i < 999,
      timestamp,
    ]
    for i, (timestamp, open_price, high, low, close, volume) in enumerate(candles)
  ]

  @app.post("/api/v1/pair_candles")
  async def pair_candles(body: dict, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    want = ["date"] + [column for column in body.get("columns") or [] if column in all_cols and column != "date"]
    indexes = [all_cols.index(column) for column in want]
    rows = [[candle[i] for i in indexes] for candle in frame][-(body.get("limit") or 1000) :]
    return {"pair": body["pair"], "timeframe": "5m", "columns": want, "data": rows, "length": len(rows)}

  @app.get("/api/v1/pair_candles")
  async def pair_candles_all(pair: str, limit: int = 1000, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    rows = frame[-limit:]
    return {"pair": pair, "timeframe": "5m", "columns": all_cols, "data": rows, "length": len(rows)}

  @app.get("/api/v1/plot_config")
  async def plot_config(authorization: str | None = Header(None)):
    _check_bearer(authorization)
    return {"main_plot": {"ema_50": {"color": "DodgerBlue"}}, "subplots": {"RSI": {"rsi_14": {"color": "orange"}}}}

  # trade actions: every call kept in app.state.calls; trade 1 is open, trade 9 closed
  app.state.data = data
  app.state.calls = []

  def _trade(trade_id: int) -> dict:
    if trade_id == 1:
      return {**data["/status"][0], "is_open": True, "amount": 12000.0}
    if trade_id == 9:
      return {"trade_id": 9, "pair": "BTC/USDT:USDT", "is_open": False, "amount": 0.01}
    raise HTTPException(404, "trade not found")

  @app.get("/api/v1/trade/{tid}")
  async def trade(tid: int, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    return _trade(tid)

  @app.post("/api/v1/forceenter")
  async def forceenter(body: dict, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    app.state.calls.append(("forceenter", body))
    if body["pair"] == "NOPE/USDT:USDT":
      return {"status": f"Error entering {body['side']} trade for pair {body['pair']}."}
    return {"trade_id": 2, "pair": body["pair"], "is_open": True}

  @app.post("/api/v1/forceexit")
  async def forceexit(body: dict, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    app.state.calls.append(("forceexit", body))
    return {"result": f"Created exit order for trade {body['tradeid']}."}

  @app.delete("/api/v1/trades/{tid}/open-order")
  async def cancel_order(tid: int, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    app.state.calls.append(("cancel", tid))
    raise HTTPException(502, "No open order for trade_id")

  @app.post("/api/v1/trades/{tid}/reload")
  async def reload_trade(tid: int, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    app.state.calls.append(("reload", tid))
    return _trade(tid)

  @app.delete("/api/v1/trades/{tid}")
  async def delete_trade(tid: int, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    app.state.calls.append(("delete", tid))
    return {"result": f"Deleted trade {tid}.", "trade_id": tid}

  @app.post("/api/v1/locks")
  async def add_locks(body: list[dict] = Body(...), authorization: str | None = Header(None)):
    _check_bearer(authorization)
    app.state.calls.append(("locks", body))
    locks = data["/locks"]["locks"]
    for lock in body:
      locks.append({"id": max((existing["id"] for existing in locks), default=0) + 1, **lock})
    data["/locks"]["lock_count"] = len(locks)
    return data["/locks"]

  @app.delete("/api/v1/locks/{lockid}")
  async def delete_lock(lockid: int, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    app.state.calls.append(("unlock", lockid))
    data["/locks"]["locks"] = [lock for lock in data["/locks"]["locks"] if lock["id"] != lockid]
    return data["/locks"]

  @app.post("/api/v1/blacklist")
  async def add_blacklist(body: dict, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    app.state.calls.append(("blacklist", body))
    blacklist = data["/blacklist"]
    errors = {
      pair: {"error_msg": f"Pair {pair} already in pairlist."}
      for pair in body["blacklist"]
      if pair in blacklist["blacklist"]
    }
    blacklist["blacklist"] += [pair for pair in body["blacklist"] if pair not in blacklist["blacklist"]]
    return {**blacklist, "errors": errors}

  @app.delete("/api/v1/blacklist")
  async def del_blacklist(pairs_to_delete: list[str] = Query([]), authorization: str | None = Header(None)):
    _check_bearer(authorization)
    app.state.calls.append(("unblacklist", pairs_to_delete))
    blacklist = data["/blacklist"]
    blacklist["blacklist"] = [pair for pair in blacklist["blacklist"] if pair not in pairs_to_delete]
    return {**blacklist, "errors": {}}

  @app.post("/api/v1/{action}")
  async def control(action: str, authorization: str | None = Header(None)):
    _check_bearer(authorization)
    states = {"start": "running", "stop": "stopped", "pause": "paused", "reload_config": "reload_config"}
    if action not in states:
      raise HTTPException(404)
    app.state.calls.append((action, None))
    data["/show_config"]["state"] = states[action] if action != "reload_config" else "running"
    return {"status": f"{action} done"}

  app.state.failing = set()  # read paths that answer 500 while listed

  def _endpoint(path, body):
    async def handler(authorization: str | None = Header(None)):
      _check_bearer(authorization)
      if path in app.state.failing:
        raise HTTPException(500)
      return body

    return handler

  for path, body in data.items():
    app.add_api_route(f"/api/v1{path}", _endpoint(path, body), methods=["GET"])

  @app.websocket("/api/v1/message/ws")
  async def ws(websocket: WebSocket, token: str | None = Query(None)):
    if token not in tokens:
      await websocket.close(code=1008)
      return
    await websocket.accept()
    subscribe = await websocket.receive_json()
    assert subscribe["type"] == "subscribe"
    try:
      while True:
        await websocket.send_json(await app.state.ws_queue.get())
    except WebSocketDisconnect:
      pass

  return app
