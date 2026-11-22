import asyncio
import gzip
import json
import zipfile

import httpx
import pytest
from nfiforge.orderflow import sources
from nfiforge.orderflow.aggregate import Minutes, big_size, merge, pick_step
from nfiforge.orderflow.db import OrderflowDb
from nfiforge.orderflow.worker import missing
from test_phase0 import _cfg, _signin

M = 60_000
T0 = 1_792_368_000_000  # a utc midnight


# =============================================================================
# AGGREGATION
# =============================================================================
def test_pick_step_is_a_nice_tick_multiple():
  assert pick_step(83_000, 0.1) == 20.0  # 2 bp of 83k = 16.6 -> 20
  assert pick_step(0.5, 0.0001) == 0.0001  # 2 bp = 0.0001: one tick
  assert pick_step(2.35, 0.0001) == 0.0005
  step = pick_step(140.0, 0.01)
  assert step >= 140 * 0.0002 and round(step / 0.01, 9) == int(round(step / 0.01))


def test_minutes_delta_path_levels_and_order():
  minutes = Minutes(step=1.0, big_usd=1000)
  minutes.add(
    [
      (T0 + 1, 100.2, 2, True),  # delta +2, first trade sets high/low
      (T0 + 2, 101.5, 1, True),  # new high at delta +3
      (T0 + 3, 99.0, 5, False),  # new low at delta -2
      (T0 + 4, 100.0, 20, True),  # big: 2000 >= 1000; delta +18
    ]
  )
  assert minutes.take() == ([], [], [])  # the minute is still open
  assert minutes.peek()[2] == [(T0 + 4, 100.0, 20, 1)]  # its big trade goes out with it, whole, each time
  minutes.add([(T0 - 10, 50.0, 1, True)])  # older than the open minute: dropped
  assert minutes.dropped == 1
  minutes.add([(T0 + M + 5, 100.0, 1, False)])
  bars, levels, big = minutes.take()
  (
    minute_start,
    open_price,
    high,
    low,
    close,
    buy_volume,
    sell_volume,
    buy_count,
    sell_count,
    delta_min,
    delta_max,
    delta_at_high,
    delta_at_low,
    max_qty,
  ) = bars[0]
  assert (minute_start, open_price, high, low, close) == (T0, 100.2, 101.5, 99.0, 100.0)
  assert (buy_volume, sell_volume, buy_count, sell_count) == (23, 5, 3, 1)
  assert (delta_min, delta_max, delta_at_high, delta_at_low, max_qty) == (-2, 18, 3, -2, 20)
  assert sorted(levels) == [(T0, 99, 0, 5, 0, 1), (T0, 100, 22, 0, 2, 0), (T0, 101, 1, 0, 1, 0)]  # rows floor the price
  assert big == [(T0 + 4, 100.0, 20, 1)]
  open_bar, open_levels, _ = minutes.peek()
  assert open_bar[0][0] == T0 + M and open_levels == [(T0 + M, 100, 0, 1, 0, 1)]


def test_merge_carries_the_delta_path_across_minutes():
  minutes = Minutes(step=1.0, big_usd=1e9)
  minutes.add([(T0, 100, 1, False), (T0 + 1, 99, 2, False)])  # minute 1: delta -3, low 99 at -3
  minutes.add([(T0 + M, 105, 10, True), (T0 + M + 1, 104, 1, False)])  # minute 2: high 105 at -3 + 10
  minutes.close()
  bars, levels, _ = minutes.take()
  (bar,) = merge(bars, levels, 5 * M)
  assert (bar["o"], bar["h"], bar["l"], bar["c"]) == (100, 105, 99, 104)
  assert (bar["dmin"], bar["dmax"], bar["dh"], bar["dl"]) == (-3, 7, 7, -3)
  assert bar["levels"][100] == [0, 1, 0, 1] and bar["levels"][105] == [10, 0, 1, 0]


# =============================================================================
# DATABASE
# =============================================================================
def test_db_rows_merge_cover_and_prune(tmp_path):
  db = OrderflowDb(tmp_path / "of.db")
  symbol = db.add_symbol("bybit", "swap", "X/USDT:USDT", 1.0, 1000)
  minutes = Minutes(1.0, 1000)
  minutes.add([(T0, 100, 1, True), (T0 + 1, 101, 2, False), (T0 + M, 103, 4, True)])
  minutes.close()
  db.write(symbol["id"], *minutes.take())
  reader = OrderflowDb(tmp_path / "of.db", readonly=True)
  out = reader.read(symbol["id"], 5 * M, T0, T0 + 5 * M, rows=2)  # rows 100,101 -> 50; 103 -> 51
  (bar,) = out["bars"]
  assert bar["levels"] == {50: [1, 2, 1, 1], 51: [4, 0, 1, 0]}
  # rewriting a range replaces it (the live open minute every second)
  more_minutes = Minutes(1.0, 1000)
  more_minutes.add([(T0, 100, 7, True)])
  more_minutes.close()
  db.write(symbol["id"], *more_minutes.take())
  assert reader.read(symbol["id"], M, T0, T0 + M, rows=1)["bars"][0]["vb"] == 7
  # cover ranges merge when they touch
  db.add_cover(symbol["id"], T0, T0 + 10 * M, "archive")
  db.add_cover(symbol["id"], T0 + 10 * M, T0 + 20 * M, "live")
  db.add_cover(symbol["id"], T0 + 30 * M, T0 + 40 * M, "live")
  assert db.covered(symbol["id"]) == [(T0, T0 + 20 * M, "live"), (T0 + 30 * M, T0 + 40 * M, "live")]
  db.prune(T0 + 35 * M)
  assert db.covered(symbol["id"]) == [(T0 + 35 * M, T0 + 40 * M, "live")]
  assert reader.read(symbol["id"], M, T0, T0 + 5 * M, rows=1)["bars"] == []


def test_missing_gaps_newest_first():
  cover = [(10, 20, "a"), (30, 40, "b")]
  assert missing(cover, 0, 50) == [(40, 50), (20, 30), (0, 10)]
  assert missing(cover, 12, 18) == []
  assert missing([], 5, 9) == [(5, 9)]


# =============================================================================
# ARCHIVES: each exchange's file layout -> (ms, price, base amount, taker bought)
# =============================================================================
def _zip(tmp_path, text):
  path = tmp_path / "f.zip"
  with zipfile.ZipFile(path, "w") as archive:
    archive.writestr("x.csv", text)
  return path


def _gz(tmp_path, text):
  path = tmp_path / "f.gz"
  path.write_bytes(gzip.compress(text.encode()))
  return path


@pytest.mark.parametrize(
  "exchange,market,text,kind,contract,expect",
  [
    (
      "binance",
      "swap",
      "agg_trade_id,price,quantity,first,last,transact_time,is_buyer_maker\n1,10.5,2,1,1,1792368000123,true\n",
      "zip",
      1,
      [(1792368000123, 10.5, 2.0, False)],
    ),
    ("binance", "spot", "1,10.5,2,1,1,1792368000123456,False,True\n", "zip", 1, [(1792368000123, 10.5, 2.0, True)]),
    (
      "bybit",
      "swap",
      "timestamp,symbol,side,size,price\n1792368000.0179,X,Sell,0.5,82065.8\n",
      "gz",
      1,
      [(1792368000017, 82065.8, 0.5, False)],
    ),
    (
      "bybit",
      "spot",
      "id,timestamp,price,volume,side,rpi\n1,1792368000188,82110.8,0.002,buy,0\n",
      "gz",
      1,
      [(1792368000188, 82110.8, 0.002, True)],
    ),
    (
      "okx",
      "swap",
      "instrument_name,trade_id,side,price,size,created_time\nX-SWAP,1,buy,0.5,13,1759248000002\n",
      "zip",
      100,
      [(1759248000002, 0.5, 1300.0, True)],
    ),
    (
      "gate",
      "swap",
      "1756684800.519701,559730057,108194.7,-3\n",
      "gz",
      0.0001,
      [(1756684800519, 108194.7, 0.0003, False)],
    ),
    ("gate", "spot", "1788220801.126324,217685954,78583.2,0.25,1\n", "gz", 1, [(1788220801126, 78583.2, 0.25, True)]),
    (
      "bitget",
      "swap",
      "trade_id,timestamp,price,side,volume(quote),size(base)\n1,1759248000000,113055,sell,293.9,0.0026\n",
      "zip",
      1,
      [(1759248000000, 113055.0, 0.0026, False)],
    ),
  ],
)
def test_archive_parsers(tmp_path, exchange, market, text, kind, contract, expect):
  (unit,) = sources.archive_units(exchange, market, "X", T0, T0 + 1)[:1]
  path = _zip(tmp_path, text) if kind == "zip" else _gz(tmp_path, text)
  got = list(sources.unit_trades([path], unit, contract))
  assert [(timestamp, price, pytest.approx(qty), buy) for timestamp, price, qty, buy in got] == expect


def test_archive_units_windows():
  day = sources.DAY
  binance = sources.archive_units("binance", "swap", "BTCUSDT", T0 + 5 * M, T0 + day + 5 * M)
  assert [(unit.start, unit.end) for unit in binance] == [(T0 + day, T0 + 2 * day), (T0, T0 + day)]  # newest first
  assert binance[0].urls[0].endswith("/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-10-20.zip")
  # okx / bitget files are utc+8 days: file D covers D-8h .. D+16h
  okx = sources.archive_units("okx", "swap", "BTC-USDT-SWAP", T0, T0 + M)
  assert [(unit.start - T0) // 3_600_000 for unit in okx] == [-8]
  assert okx[0].urls[0].endswith("/20261019/BTC-USDT-SWAP-trades-2026-10-19.zip")
  gate = sources.archive_units("gateio", "swap", "BTC_USDT", T0, T0 + M)  # freqtrade's name for gate
  assert gate[0].urls[0].endswith("/futures_usdt/trades/202610/BTC_USDT-202610.csv.gz")
  assert len(sources.archive_units("bitget", "swap", "BTCUSDT", T0, T0 + M)[0].urls) > 1  # numbered parts
  assert sources.archive_units("kraken", "spot", "XBTUSD", T0, T0 + M) == []


# =============================================================================
# REST PAGER (fake exchanges with the real apis' habits)
# =============================================================================
class FakeEx:
  # trades every 10 ms from T0 for 10 s; page size 1000 like the real ones
  def __init__(self, id, newest_first=True, seconds=False, refuse_before=None):
    self.id, self.newest_first, self.seconds, self.refuse_before = id, newest_first, seconds, refuse_before
    self.trades = [
      {"id": str(i), "timestamp": T0 + i * 10, "price": 1.0, "amount": 1.0, "side": "buy"} for i in range(1000 * 1)
    ]
    self.trades += [
      {"id": f"b{i}", "timestamp": T0 + 10_000 + i * 2, "price": 1.0, "amount": 1.0, "side": "sell"}
      for i in range(3000)
    ]
    self.calls = 0

  async def fetch_trades(self, symbol, since=None, limit=1000, params=None):
    self.calls += 1
    until = (params or {}).get("until")
    if self.seconds and until is not None:
      until = until // 1000 * 1000  # the api takes whole seconds
    if self.refuse_before is not None and since is not None and since < self.refuse_before:
      raise sources.ccxtpro.BadRequest("too long ago")
    rows = [
      trade
      for trade in self.trades
      if (since is None or trade["timestamp"] >= since) and (until is None or trade["timestamp"] < until)
    ]
    if self.id == "binance":
      return rows[:limit]
    if since is None and until is None:
      return rows[-limit:]
    return rows[-limit:] if self.newest_first else rows[:limit]


@pytest.mark.parametrize(
  "ex", [FakeEx("binance"), FakeEx("gate", seconds=True), FakeEx("bitget"), FakeEx("bitvavo", newest_first=False)]
)
async def test_rest_pager_gets_every_trade(ex):
  first, last, out = await sources.rest_trades(ex, "X", T0, T0 + 20_000, 1.0)
  assert (first, last) == (T0, T0 + 20_000)
  assert len(out) == 4000 and len({(trade[0], trade[3]) for trade in out}) > 0
  assert [trade[0] for trade in out] == sorted(trade[0] for trade in out)


async def test_rest_pager_stops_where_the_api_refuses():
  exchange = FakeEx("binance", refuse_before=T0 + 5_000)
  assert await sources.rest_trades(exchange, "X", T0, T0 + 20_000, 1.0) == (T0 + 20_000, T0 + 20_000, [])


async def test_rest_recent_only_starts_at_a_whole_minute():
  exchange = FakeEx("kucoin")
  first, last, out = await sources.rest_trades(exchange, "X", T0, T0 + 20_000, 1.0)
  assert first >= T0 + 20_000 or first % M == 0  # latest 1000 trades start mid-minute: complete from the next minute


# =============================================================================
# ROUTES
# =============================================================================
async def test_off_means_absent(fake, tmp_path):
  _, url, _ = fake
  from nfiforge.app import create_app

  config = _cfg(url)
  config.data_dir = str(tmp_path)
  app = create_app(config)
  local = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=local, base_url="http://t") as client:
    assert (await client.get("/api/health")).json()["orderflow"] is False
    await _signin(app, client, role="viewer")
    assert (await client.get("/api/orderflow/status")).status_code == 404
  assert not (tmp_path / "orderflow").exists()


async def test_bars_watch_the_pair_and_read_the_db(fake, tmp_path, monkeypatch):
  _, url, _ = fake
  from nfiforge.app import create_app
  from nfiforge.orderflow import routes

  async def no_worker(self):
    return None

  monkeypatch.setattr(routes.Orderflow, "_run", no_worker)
  config = _cfg(url)
  config.data_dir = str(tmp_path)
  config.orderflow.enabled = True
  app = create_app(config)
  local = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=local, base_url="http://t") as client:
    await _signin(app, client, role="viewer")
    for _ in range(100):  # the bot's config (exchange) arrives with its first poll
      response = await client.get("/api/orderflow/bars", params={"bot": "Fake", "pair": "BTC/USDT:USDT", "tf": "5m"})
      if response.status_code == 200:
        break
      await asyncio.sleep(0.05)
    assert (
      response.json()["pending"] is True
      and response.json()["exchange"] == "bybit"
      and response.json()["market"] == "swap"
    )
    await asyncio.sleep(2.2)  # watch.json is shared every 2 s
    watch = json.loads((tmp_path / "orderflow" / "watch.json").read_text())
    assert {"exchange": "bybit", "market": "swap", "symbol": "BTC/USDT:USDT"} in watch["pairs"]
    # the worker's rows come back as bars
    db = OrderflowDb(tmp_path / "orderflow" / "orderflow.db")
    symbol = db.add_symbol("bybit", "swap", "BTC/USDT:USDT", 20.0, 40_000)
    minutes = Minutes(20.0, 40_000)
    minutes.add([(T0, 83_000, 1, True), (T0 + M, 83_050, 2, False)])
    minutes.close()
    db.write(symbol["id"], *minutes.take())
    db.add_cover(symbol["id"], T0, T0 + 2 * M, "archive")
    response = (
      await client.get(
        "/api/orderflow/bars",
        params={"bot": "Fake", "pair": "BTC/USDT:USDT", "tf": "5m", "start": T0 / 1000, "end": (T0 + 5 * M) / 1000},
      )
    ).json()
    assert response["pending"] is False and response["step"] == 20.0 and len(response["bars"]) == 1
    assert response["bars"][0]["levels"] == {"4150": [1, 0, 1, 0], "4152": [0, 2, 0, 1]}
    assert response["cover"] == [{"start": T0, "end": T0 + 2 * M, "source": "archive"}]
    assert (await client.get("/api/orderflow/bars", params={"bot": "Fake", "pair": "X", "tf": "2m"})).status_code == 400
    assert (await client.get("/api/orderflow/sources")).status_code == 200
    bad = {"bot": "Fake", "pair": "BTC/USDT", "tf": "5m", "market": "x"}
    assert (await client.get("/api/orderflow/bars", params=bad)).status_code == 400
    spot = (await client.get("/api/orderflow/bars", params=bad | {"market": "spot"})).json()
    assert spot["pending"] is True and spot["market"] == "spot"  # the spot pair is watched on the bot's exchange
    # the tape: the worker's latest trades file, as written
    params = {"bot": "Fake", "pair": "BTC/USDT:USDT"}
    assert (await client.get("/api/orderflow/tape", params=params)).json() == {
      "pending": False,
      "trades": [],
      "big_usd": 40_000,
      "step": 20.0,
    }
    (tmp_path / "orderflow" / "live").mkdir(exist_ok=True)
    (tmp_path / "orderflow" / "live" / f"{symbol['id']}.tape.json").write_text(
      json.dumps({"ts": T0, "trades": [[T0, 83_000, 1, True]]})
    )
    assert (await client.get("/api/orderflow/tape", params=params)).json()["trades"] == [[T0, 83_000, 1, True]]
    assert (await client.get("/api/orderflow/book", params=params)).json()["last"] == [T0, 83_000, 1, True]
    # open interest, liquidations, funding per bar
    db.write_derivs(symbol["id"], open_interest=[(T0, 5.0)], liqs=[(T0, 83_000, 0.5, 1)])
    response = (
      await client.get(
        "/api/orderflow/derivs", params=params | {"tf": "5m", "start": T0 / 1000, "end": (T0 + 5 * M) / 1000}
      )
    ).json()
    assert response["oi"] == [[T0, 5.0]] and response["liq"] == [[T0, 41_500.0, 0, 1]] and response["funding"] == []


# =============================================================================
# ORDER BOOK
# =============================================================================
from nfiforge.orderflow import book  # noqa: E402


def test_column_encode_round_trip():
  bids, asks = [(100.4, 2.0), (100.1, 1.0), (99.0, 5.0)], [(100.6, 3.0), (101.2, 0.5)]
  low_row, bid_sizes, ask_sizes = book.column(bids, asks, 1.0)
  assert low_row == 100 - book.SPAN_ROWS
  assert (
    bid_sizes[100 - low_row] == 3.0
    and bid_sizes[99 - low_row] == 5.0
    and ask_sizes[100 - low_row] == 3.0
    and ask_sizes[101 - low_row] == 0.5
  )
  decoded_low, decoded_bids, decoded_asks = book.decode(book.encode(low_row, bid_sizes, ask_sizes))
  assert (
    decoded_low == 99
    and decoded_bids == pytest.approx([5.0, 3.0, 0.0], rel=3e-3)
    and decoded_asks == pytest.approx([0.0, 3.0, 0.5], rel=3e-3)
  )
  assert book.decode(book.encode(0, [0.0], [0.0])) == (0, [], [])


def test_bands_only_where_the_book_reaches():
  bids = [(99.95, 1.0), (99.5, 2.0), (98.0, 1.0)]  # reaches 2 % down
  asks = [(100.05, 1.0), (100.3, 1.0)]  # reaches 0.3 % up
  mid, values = book.bands(bids, asks)
  assert mid == 100.0
  # 0.1 %: bid 99.95, ask 100.05; 0.2 %: same; 0.5 %: bids 99.95 + 99.5, asks beyond reach -> None
  assert values[0] == pytest.approx(99.95) and values[1] == pytest.approx(100.05)
  assert values[4] == pytest.approx(99.95 + 199.0) and values[5] is None
  assert values[10] is None and values[11] is None  # 5 %: neither side reaches


def test_walls_need_to_rest_then_pulled_or_filled():
  walls = book.Walls(usd=1000)
  bid = [(100.0, 20.0)]  # $2000
  assert walls.update(0, bid, [], {}) == []  # not yet resting long enough
  assert walls.update(10_000, bid, [], {}) == [(10_000, 100.0, 20.0, 1, "appear")]
  assert walls.update(11_000, [(100.0, 5.0)], [], {100.0: 1.0}) == [(11_000, 100.0, 15.0, 1, "pulled")]
  walls.update(12_000, [(101.0, 20.0)], [], {})
  walls.update(22_000, [(101.0, 20.0)], [], {})
  assert walls.update(23_000, [], [], {101.0: 18.0}) == [(23_000, 101.0, 20.0, 1, "filled")]
  walls.update(30_000, [], [(102.0, 30.0)], {})
  assert walls.update(30_500, [], [], {}) == []  # gone before it counted: no event


def test_replay_bybit_and_gate(tmp_path):
  lines = [
    {"type": "snapshot", "ts": T0 + 500, "data": {"b": [["99", "1"], ["98", "2"]], "a": [["101", "3"]]}},
    {"type": "delta", "ts": T0 + 9_000, "data": {"b": [["99", "0"], ["99.5", "4"]], "a": []}},
    {"type": "delta", "ts": T0 + 21_000, "data": {"b": [], "a": [["101", "1"]]}},
  ]
  bybit_path = tmp_path / "ob.zip"
  with zipfile.ZipFile(bybit_path, "w") as archive:
    archive.writestr("x.data", "\n".join(json.dumps(line) for line in lines))
  frames = list(book.replay_bybit(bybit_path, 1.0))
  assert frames == [
    (T0 + 10_000, [(99.5, 4.0), (98.0, 2.0)], [(101.0, 3.0)]),
    (T0 + 20_000, [(99.5, 4.0), (98.0, 2.0)], [(101.0, 3.0)]),
  ]
  gate_path = tmp_path / "g.gz"
  gate_path.write_bytes(
    gzip.compress(
      b"".join(
        [
          f"{T0 / 1000},set,99,10,1,0\n".encode(),
          f"{T0 / 1000},set,101,-5,1,0\n".encode(),
          f"{(T0 + 12_000) / 1000},make,99,2,1,0\n".encode(),
          f"{(T0 + 15_000) / 1000},take,101,-5,1,0\n".encode(),
          f"{(T0 + 15_000) / 1000},make,102,-1,1,0\n".encode(),
          f"{(T0 + 31_000) / 1000},make,98,1,1,0\n".encode(),
        ]
      )
    )
  )
  frames = list(book.replay_gate(gate_path, 0.1))
  assert frames[0] == (T0 + 10_000, [(99.0, 1.0)], [(101.0, 0.5)])
  assert frames[-1] == (T0 + 30_000, [(99.0, pytest.approx(1.2))], [(102.0, pytest.approx(0.1))])


def test_binance_depth_bands(tmp_path):
  rows = "timestamp,percentage,depth,notional\n" + "".join(
    f"2026-10-19 00:00:01,{pct},1,{depth}\n"
    for pct, depth in (("-0.20", 5), ("0.20", 4), ("-1.00", 50), ("1.00", 40), ("-5.00", 500), ("5.00", 400))
  )
  ((timestamp, depth),) = book.read_binance_depth(_zip(tmp_path, rows))
  assert timestamp == 1792368001000
  assert depth == [None, None, 5, 4, None, None, 50, 40, None, None, 500, 400]


def test_heat_averages_columns_per_slot(tmp_path):
  db = OrderflowDb(tmp_path / "of.db")
  symbol_id = db.add_symbol("bybit", "swap", "X/USDT:USDT", 1.0, 1000)["id"]
  first_column = book.encode(*book.column([(100.0, 2.0)], [(102.0, 4.0)], 1.0))
  second_column = book.encode(*book.column([(100.0, 4.0)], [(102.0, 4.0)], 1.0))
  db.write_book(
    symbol_id,
    [(T0, first_column), (T0 + 10_000, second_column)],
    [(T0, 101.0, [1, 2] * 6)],
    [(T0, 100.0, 9.0, 1, "appear")],
  )
  out = OrderflowDb(tmp_path / "of.db", readonly=True).heat(symbol_id, M, T0, T0 + M, per_bar=1, rows=1)
  (col,) = out["cols"]
  assert (
    col["lo"] == 100 and col["b"][0] == pytest.approx(3.0, rel=1e-3) and col["a"][2] == pytest.approx(4.0, rel=1e-3)
  )
  assert out["imb"] == [{"t": T0, "v": [1, 2] * 6}] and out["events"] == [(T0, 100.0, 9.0, 1, "appear")]
  out2 = OrderflowDb(tmp_path / "of.db", readonly=True).heat(symbol_id, M, T0, T0 + M, per_bar=6, rows=2)
  assert len(out2["cols"]) == 2 and out2["cols"][0]["lo"] == 50  # rows merged 2 at a time, 10 s slots


# =============================================================================
# OPEN INTEREST, FUNDING, LIQUIDATIONS
# =============================================================================
from nfiforge.orderflow import derivs  # noqa: E402


def test_liquidated_side_per_exchange():
  # bybit / gate report the position side, the others the liquidation order (a sell closes a long)
  assert derivs.long_liquidated("bybit", "buy") and not derivs.long_liquidated("bybit", "sell")
  assert derivs.long_liquidated("gate", "buy")
  for exchange in ("binance", "okx", "htx"):
    assert derivs.long_liquidated(exchange, "sell") and not derivs.long_liquidated(exchange, "buy")
  rows = derivs.liq_rows(
    "okx",
    [
      {"timestamp": T0, "price": 100.0, "contracts": 20, "side": "sell"},
      {"timestamp": T0 + 1, "price": 101.0, "contracts": 10, "side": "buy"},
      {"timestamp": None, "price": 1.0, "contracts": 1, "side": "buy"},  # incomplete: skipped
    ],
    0.01,
  )
  assert rows == [(T0, 100.0, 0.2, 1), (T0 + 1, 101.0, 0.1, 0)]


class _OiEx:
  # pages forward from `since`, 2 points a page; 5m refused like htx when `refuse_5m`
  def __init__(self, count: int, refuse_5m: bool = False):
    self.has = {"fetchOpenInterestHistory": True}
    self.points = [T0 + index * 5 * M for index in range(count)]
    self.refuse_5m, self.calls = refuse_5m, []

  async def fetch_open_interest_history(self, symbol, timeframe, since=None, limit=None):
    self.calls.append((timeframe, since))
    if timeframe == "5m" and self.refuse_5m:
      raise derivs.ccxtpro.BadRequest("1h and up only")
    page = [timestamp for timestamp in self.points if timestamp >= since][:2]
    return [{"timestamp": timestamp, "openInterestAmount": 1000 + index} for index, timestamp in enumerate(page)]


async def test_oi_history_pages_forward_in_base_units():
  exchange = _OiEx(5)
  got = await derivs.oi_history(exchange, "X", T0, 0.01)
  assert [timestamp for timestamp, _ in got] == exchange.points and got[0][1] == pytest.approx(10.0)
  assert [since for _, since in exchange.calls] == [T0, T0 + 5 * M + 1, T0 + 15 * M + 1, T0 + 20 * M + 1]
  exchange = _OiEx(3, refuse_5m=True)
  assert (
    len(await derivs.oi_history(exchange, "X", T0, 1.0)) == 3
    and exchange.calls[0][0] == "5m"
    and exchange.calls[1][0] == "1h"
  )
  assert await derivs.oi_history(type("E", (), {"has": {}})(), "X", T0, 1.0) == []


def test_db_derivs_per_bar_and_prune(tmp_path):
  db = OrderflowDb(tmp_path / "of.db")
  symbol_id = db.add_symbol("bybit", "swap", "BTC/USDT:USDT", 1.0, 1000)["id"]
  db.write_derivs(
    symbol_id,
    open_interest=[(T0, 10.0), (T0 + 2 * M, 12.0), (T0 + 5 * M, 15.0)],
    funding=[(T0 - 8 * 60 * M, 0.0001), (T0 + 4 * M, -0.0002)],
    liqs=[(T0 + M, 100.0, 2.0, 1), (T0 + 2 * M, 50.0, 1.0, 0), (T0 + 6 * M, 10.0, 1.0, 1)],
  )
  out = db.derivs(symbol_id, 5 * M, T0, T0 + 10 * M)
  assert out["oi"] == [(T0, 12.0), (T0 + 5 * M, 15.0)]  # the bar's last point
  assert out["liq"] == [[T0, 200.0, 50.0, 2], [T0 + 5 * M, 10.0, 0.0, 1]]
  assert out["funding"] == [[T0 - 8 * 60 * M, 0.0001], [T0 + 4 * M, -0.0002]]  # the rate in force at the start too
  assert db.last_ts(symbol_id, "oi") == T0 + 5 * M and db.last_ts(symbol_id, "liqs") == T0 + 6 * M
  db.prune(T0 + 5 * M)
  out = db.derivs(symbol_id, 5 * M, T0 - 10 * 60 * M, T0 + 10 * M)
  assert out["oi"] == [(T0 + 5 * M, 15.0)] and len(out["liq"]) == 1 and out["funding"] == []


def test_big_size_top_share_or_fixed():
  values = [float(value) for value in range(1, 10_001)]  # 1 .. 10000 usd
  assert big_size(values, 0.5) == 9950.0  # the top 0.5 %
  assert big_size(values[:200], 0.5) == 1000.0  # never under 1000
  assert big_size([value * 10 for value in values], 0.5) == pytest.approx(99_500)
  assert big_size([value * 10 for value in values], 2) == pytest.approx(98_000)
  assert big_size(values, 0.5, fixed=250) == 250  # a fixed size wins
  assert big_size(values[:50], 0.5) is None  # too few trades


async def test_settings_page_changes_the_running_options(fake, tmp_path, monkeypatch):
  _, url, _ = fake
  from nfiforge.app import create_app
  from nfiforge.orderflow import routes

  async def no_worker(self):
    return None

  monkeypatch.setattr(routes.Orderflow, "_run", no_worker)
  config = _cfg(url)
  config.data_dir = str(tmp_path)
  config.orderflow.enabled = True
  config.orderflow.max_pairs = 7
  app = create_app(config)
  local = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=local, base_url="http://t") as client:
    await _signin(app, client)
    status = (await client.get("/api/orderflow/status")).json()
    assert status["settings"]["max_pairs"] == 7 and status["settings"]["big_pct"] == 0.5 and status["memory_mb"] == 1024
    settings = (await client.get("/api/settings")).json()
    settings["orderflow"] = {"max_pairs": 3, "big_usd": 5000, "memory_mb": 512, "enabled": False}
    assert (await client.put("/api/settings", json=settings)).status_code == 200
    status = (await client.get("/api/orderflow/status")).json()
    assert status["settings"]["max_pairs"] == 3 and status["settings"]["big_usd"] == 5000 and status["memory_mb"] == 512
    assert (
      status["defaults"]["max_pairs"] == 7
      and status["defaults"]["memory_mb"] == 1024
      and "enabled" not in status["defaults"]
    )
    settings["orderflow"] = {"max_pairs": 0}  # out of range: refused, nothing changes
    response = await client.put("/api/settings", json=settings)
    assert response.status_code == 422 and "max_pairs" in response.json()["detail"]
    assert (await client.get("/api/orderflow/status")).json()["settings"]["max_pairs"] == 3
  # a restart starts with the saved changes
  app = create_app(config)
  async with app.router.lifespan_context(app), httpx.AsyncClient(transport=local, base_url="http://t") as client:
    await _signin(app, client)
    assert (await client.get("/api/orderflow/status")).json()["settings"]["max_pairs"] == 3
    # reset on the settings page: config.yaml's options again
    settings = (await client.get("/api/settings")).json()
    settings["orderflow"] = {}
    assert (await client.put("/api/settings", json=settings)).status_code == 200
    status = (await client.get("/api/orderflow/status")).json()
    assert status["settings"]["max_pairs"] == 7 and status["settings"]["big_usd"] == 0 and status["memory_mb"] == 1024
