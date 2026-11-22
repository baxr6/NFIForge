# Order Flow page: design (21/10/2026; steps 1-4 built)

One page, **Order Flow** (`/orderflow`), that shows trades (footprint) and resting orders
(order book) for one pair at a time, at the standard of ATAS, Bookmap, Exocharts and Sierra
Chart. Built from free public exchange data only. No trading logic, display only.

## 1. Data sources (all public, no keys)

Every exchange NostalgiaForInfinity ships configs for. Live = the exchange's public trade stream through ccxt pro
(any exchange ccxt supports). History, best first: the exchange's own free archive files, else its rest api paged
through time, else only its latest trades (history then starts when recording starts; the chart marks the hole).
Checked 21/10/2026 against each exchange's own candles and against its rest trades trade-for-trade.

| Exchange | Live | Archive files | Rest api reaches back |
|---|---|---|---|
| Binance (futures + spot) | yes | data.vision daily aggTrades, all history | futures 2 days, spot all (paged forward) |
| Bybit (futures + spot) | yes | public.bybit.com daily files, up to yesterday | latest 1000 trades only |
| OKX (swap + spot) | yes | static.okx.com daily files (utc+8 days), up to yesterday | ~3 months (history endpoint, 100 per call) |
| Gate (futures + spot) | yes | download.gatedata.org monthly files, finished months only | futures: this month; spot 30 days |
| Bitget (futures + spot) | yes | img.bitgetimg.com daily files (utc+8, numbered parts); stops mid-Aug 2026 | ~90 days |
| Hyperliquid | yes | none free (s3 requester-pays) | none (no public trade list) |
| Kraken, Kraken Futures | yes | none | all (paged forward) |
| Bitvavo | yes | none | all (paged back) |
| KuCoin, MEXC, HTX | yes (MEXC needs protobuf) | none | latest trades only |
| Bitmart | no (not in this ccxt) | none | none |

Not built yet (later steps): order book (Bybit ob500 / Binance bookDepth archives, live book stream), open
interest, funding, liquidations.

## 2. Backend: `orderflow` worker (new, `backend/nfiforge/orderflow/`)

Same pattern as the BTCGate worker: a separate process, off by default, its own memory limit,
on/off switch in Settings.

- **Recorder**: one websocket per exchange, subscribes only to *watched* pairs:
  the pair open on the page + pairs with open trades on any bot (optional, setting) + a
  user list. Max pairs setting (default 10). Unsubscribes 10 min after nobody looks.
- **Level store** (the footprint itself), per 1-min bar x price level: bid vol, ask vol,
  trades at bid, trades at ask. Every coarser timeframe (5m, 15m, 1h, 4h, 1d) is summed
  from the 1-min store, so no re-download for a new timeframe. Price bucket = tick size x N,
  chosen per pair so a typical bar has 20-40 rows; user can change the row size on the chart.
- **Book store**: full book kept in memory; every 1 s a snapshot of the top N levels
  (default 400) is quantised to the row size and appended (heatmap source). Large-order
  events (order appears / pulled / filled at a level >= X x average size) stored as rows.
- **History fill**: on first look at a pair, yesterday and earlier come from the daily
  trade files (streamed, never kept raw); today before the recorder started is a gap,
  marked on the chart. Book history only exists from recording start (or optional
  ob500 import per day, off by default: ~100s of MB per pair-day).
- **Storage**: SQLite (WAL) per pair-month under `data/orderflow/`, retention setting
  (default 30 days level store, 7 days book snapshots). Disk shown in Settings.
- **API**: `GET /api/orderflow/{pair}/bars?tf&from&to` (bars + levels + bar stats),
  `/book/heatmap?from&to&rows`, `/book/now`, `/events`, `/profile?from&to`;
  live push over the existing hub websocket (`of_trade`, `of_book`, `of_bar`), throttled
  to 4 updates/s per pair.

## 3. Page layout (desktop; phone = one view at a time with tabs)

```
+-----------------------------------------------------------+---------+
| toolbar: bot | pair | tf | view | row size | presets | rec |         |
+-----------------------------------------------------------+   DOM   |
|                                                           |  ladder |
|   MAIN CHART  (heatmap behind, candles/footprint on top,  |         |
|   bubbles, volume profile on the right edge, zones,       |  bids | |
|   VWAP bands, trade marks from the bot)                   |  price| |
|                                                           |  asks | |
+-----------------------------------------------------------+         |
| CVD / delta panel                                         |---------|
+-----------------------------------------------------------+  T&S    |
| OI + funding + liquidations panel                         |  tape   |
+-----------------------------------------------------------+---------+
| footer: bar stats table for the hovered bar               | depth   |
+-----------------------------------------------------------+---------+
```

Panels use the existing PanelGrid (movable, saved per user, reset to default).

## 4. Main chart: everything it can show (each one a toggle)

Rendered with lightweight-charts v5 custom series + primitives (already a dependency),
so zoom, crosshair and time axis match the existing Chart page.

### Footprint cell styles (switch)
1. **Bid x Ask** (`120 x 340` per row), diagonal imbalance highlight.
2. **Delta** per row, colour by sign, intensity by size.
3. **Volume** per row, histogram bar inside the cell.
4. **Trades count** bid x ask.
5. **Profile in candle**: per-bar volume histogram, bid/ask split.
Auto-degrades by zoom: cells -> mini profile -> plain candle with delta colour.

### Per-bar marks
- POC row (box), value area (70 %, bracket), bar delta + volume under the bar.
- **Imbalances**: diagonal ratio (default 300 %) + min volume; **stacked** (>= 3 in a row)
  drawn as a zone that extends right until price trades back through it.
- **Unfinished auction** (both sides traded at the extreme) dot; revisit target line.
- **Exhaustion print** (tiny volume at the extreme), **absorption** (heavy aggression at
  the bar end, no progress), **delta divergence** (new high on lower CVD, mirror).
- **COT high/low** (cumulative delta at the moment of the bar high/low).
- **Big trades**: bubbles sized by notional, green/red by side, threshold = rolling 99th
  pct per pair or fixed USD.

### Order book layer
- **Liquidity heatmap** behind the candles (Bookmap style): time x price, colour =
  resting size, scale auto/manual, contrast slider, log/linear. Walls show as bright
  bands; pulled walls fade, eaten walls end at the price line.
- **Large order markers**: appear / pulled / filled icons on the heatmap.
- **Book imbalance** line (bid vs ask size within +-0.5/1/2 %), in the lower panel.

### Profiles and levels
- **Volume profile** on the right: visible range, session (UTC day), or fixed range drawn
  by the user; bid/ask or delta split; POC, VAH/VAL, HVN/LVN marks.
- **Developing POC / VA** lines through the session.
- **Session VWAP** + 1/2 sigma bands; anchored VWAP from any click.
- **Bot trades** from the selected bot: entry, adds, exits, liquidation price, stop.

## 5. Side and lower panels

- **DOM ladder**: price rows, bid size | price | ask size, cumulative toggle, last trade
  flash, traded volume at price (session), big-order highlight, centre on price.
  Display only (no click-to-trade; trading stays on the Positions page).
- **Time & Sales tape**: time, side, price, size, notional; big trades highlighted;
  filter by min size; aggregated (same-ms) or raw.
- **Depth chart**: cumulative bid/ask mountain, +-1/2/5 % range.
- **CVD / delta**: bar delta histogram + CVD line (session reset or continuous),
  optional spot vs perp CVD (Binance spot, majors only, later).
- **OI + funding + liquidations**: OI line, delta x OI quadrant colour per bar
  (longs/shorts opening/closing), funding, liquidation bars by side.
- **Bar stats table** (hovered bar): volume, delta, delta %, min/max delta, trades,
  avg/max size, POC, VA, imbalances, stacked count, big-trade share, OI change.

## 6. Settings (Order Flow section)
On/off, memory limit, max pairs, watch open-trade pairs, retention, row size default,
imbalance ratio + min volume, big trade threshold, heatmap levels + snapshot rate,
colour theme (uses the app theme; colour-blind safe pair option).

## 7. Out of scope (stated so nothing is assumed)
- Click-to-trade from the DOM.
- Iceberg / spoof *detection labels* (the heatmap shows pulled orders; labelling them
  needs its own test first).
- Any signal, alert or bot input from this data: research first, page second
  (order-flow direction failed 4 tests, footprint classic reads failed; the page is a
  viewing tool, not a claimed edge).
- Multi-venue aggregated book (Bybit only first).

## 8. Build order (each step releasable)
1. Worker + recorder + level store + trades API; page with footprint (all cell styles,
   POC/VA, imbalances, stacked zones, CVD panel, bar stats). History fill from daily files.
2. Book store + heatmap + DOM + depth chart + large-order markers + book imbalance.
3. Profiles (visible/session/fixed), VWAP bands, unfinished auctions, exhaustion,
   absorption, divergence, bubbles, tape.
4. OI / funding / liquidations panel, bot-trade overlay, phone layout polish.

### Step 3 as built (22/10/2026)
All read in the browser from the footprint bars (`lib/orderflow.ts`), except the tape, which reads the worker's
latest 500 trades (`live/<sym>.tape.json`, `/api/orderflow/tape`). Mark rules, at the stored row size, and how often
they fired on BTW and DOGE 5m-1h:
- Unfinished auction: both sides traded the extreme row; line until price trades beyond it (25-60 %, standard rule).
- Exhaustion: aggressive side in the extreme row < 5 % of the bar's average row, next row in >= half (3-13 %).
- Absorption: >= 35 % of the bar's buying (selling) in its top (bottom) fifth of rows, that side leading there, close
  in the other half (3-10 %).
- Delta divergence: high (low) beyond the last 20 bars with cumulative delta below (above) that earlier extreme (2-7 %).
- Delta at high / low (COT): the running delta stored per minute (`dh`, `dl`), shown when numbers fit.
- High / low volume nodes: peaks / troughs of the profile smoothed over ~1/40 of its rows, within ~1/12 of its rows;
  a peak above the average row, a trough under half of it and between two peaks.
- Range profile and anchored VWAP: bars picked by clicking the chart; reset on a new pair.

### Step 4 as built (22/10/2026)
- Perpetuals only. Open interest each minute (history first where the exchange keeps it: bybit / binance / okx / gate
  5 min, htx 1 h, kucoin latest page only; bitget / hyperliquid live only; mexc none), in base units (ccxt gives
  contracts). Settled funding every 10 min plus the next rate. Liquidations live from when the pair is watched: a
  stream on binance / bybit / okx (binance sends one per pair per second at most), polled every 30 s on gate / htx.
  `side` differs: bybit and gate report the position (buy = a long liquidated), the others the order (sell = a long
  liquidated); checked live 22/10 on one BTC burst seen on all three streams. Code: `orderflow/derivs.py`.
- Panes: open interest change per bar coloured by price x OI (longs / shorts opening / closing) with the OI line;
  liquidated longs (down) / shorts (up) with the settled funding line. Each pane exists only while it has data.
- Bot trades: the Chart page's marks and lines (`lib/trades.ts` pairMarks / overlay, `charts/tradeMarks.ts`), plus
  the open trade's stop when it fires before liquidation.
- Phones: tabs (Chart / DOM / Tape / Depth), one full height; the switches fold under "layers".
- Settings page (22/10): Order Flow section edits the recorder's options over config.yaml's (saved with the app
  settings, checked against OrderflowConfig, reach the worker within 30 s); on / off stays in config.yaml. App-wide
  colour-blind up / down colours (sky blue / vermillion). Heatmap levels and the 10 s snapshot stay fixed.
- Also 22/10: heatmap log / linear and a manual full-brightness size; DOM flashes the latest trade's row; big-trade
  size rolls (top big_pct % of the last ~20k trades, every 10 min) or is fixed (big_usd); spot CVD next to the perp's
  (the spot pair on the bot's exchange, recorded while the switch is on).

## 9. Resource estimate (to confirm in step 1)
Bybit trade stream for 10 active alts: a few hundred msgs/s peak. 1-min level store
~1-3 MB per pair-day. Book snapshots at 400 levels x 1 s: ~20-40 MB per pair-day
uncompressed -> stored quantised + zlib, target < 10 MB. Worker memory target < 300 MB.
