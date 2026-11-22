# BTCGate in NFIForge

BTCGate runs inside NFIForge instead of as a freqtrade bot (nexusforge). Optional, off by default, contained in its own
folders, with one master switch in `config.yaml` and its own settings and pages once on.

Status: built. Master switch, supervisor, worker, the Market / Coins / Ledger / Signals / Scanner / Book tabs, settings,
alerts and Positions badges are all in (section 8).

## 1. Principles

- **One copy of the research code.** The BTCGate repo stays the source of the modules. NFIForge installs it as a
  package (`pip install nfiforge[btcgate]`); NFIForge's `btcgate/` folders only hold the glue. A copy would drift and
  the live signals would stop being the backtested code.
- **BTCGate never knows about NFIForge or NFI.** Dependency points one way.
- **Off means absent.** Master switch off: the package isn't imported, no worker, no routes, no menu, no badges.
- **Its own process.** BTCGate needs up to ~4 GB for ~150 coins; NFIForge runs at ~260 MB. A worker process keeps a
  BTCGate crash or memory spike away from the dashboard.
- **Same signals as today.** Before nexusforge is switched off, both run side by side and must produce the same
  signals (parity check). The ledger clock only continues if they match.

## 2. Layout

```
NFIForge/
  backend/nfiforge/btcgate/      # everything backend, only imported when btcgate.enabled
    worker.py                    # the runner: pairs, candles, 5 min loop, writes the db
    supervisor.py                # starts / stops / restarts the worker, memory limit, health
    routes.py                    # /api/btcgate/... (read the db, settings)
    settings.py                  # (0.28) module switches, alert routing (push / telegram per alert type)
    hooks.py                     # (0.28) the few things other pages ask for (badges per pair, events)
  frontend/src/btcgate/          # pages, panels, store; the route and menu entry only exist when on
  docs/BTCGATE.md                # this file

<install>/data/btcgate/          # data, not code: inside the NFIForge install, e.g. ~/nfiforge/data/btcgate
                                 # (always NFIForge's data_dir + /btcgate, so it moves and backs up with the install)
  btcgate.json, btcgate_secret.json   # btcgate's settings; keys and tokens merged in from the secret file (chmod 600)
  btcgate_monitor.sqlite, btcgate_binance.sqlite
  candles/                       # pickle per coin and timeframe so a restart doesn't refetch 2,450 candles x 150 coins
  status.json, snapshot.json     # worker health; each coin's latest labels (what the pages read)
  worker.log                     # rotated at 20 MB
```

Outside those folders, one guarded line each: the router include, the menu entry, the Positions badge slot, the event
stream feed, the alert hand-off to push.

Docker installs (install.sh): not yet. The image would need the btcgate package and a memory limit
that allows for the worker; install.sh should ask when BTCGate is turned on.

Measured on the first build (150 coins, Binance): first start 6 min of candles plus a few minutes for btcgate's own
Binance store, restart 11 s from the cache, 1.5 min per pass, labels 1-2 min after each 5 min candle, ~600 MB.

## 3. Master switch

```yaml
btcgate:
  enabled: false        # starts the worker; restart nfiforge after changing
  memory_mb: 4096       # worker is killed and restarted above this
```

In `config.yaml`, not the web Settings: it starts a heavy process, so it's a server decision (same as `write_actions`).

## 4. What the worker takes over from freqtrade

BTCGateMonitor (2,070 lines) uses freqtrade for these jobs; the worker does them itself:

| Job | freqtrade today | Worker |
|---|---|---|
| Coin list | VolumePairList, AgeFilter, PriceFilter, SpreadFilter, RangeStabilityFilter (Binance futures) | same filters on Binance futures tickers; the list is logged each refresh so it can be compared with nexusforge |
| Candles | 5m, 15m, 1h, 4h, 1d + funding, 2,450 startup candles per coin | 5m, 1h, 4h from Binance (ccxt), closed candles, gaps filled like freqtrade, kept in memory, cached to disk; only new candles fetched each pass. 15m, 1d and funding come from btcgate's own Binance store (`source.signals: binance`); with `exchange` the worker fetches 15m and 1d too |
| Loop | `bot_loop_start` + `populate_indicators` per coin every 5 min | every 5 min after the candle closes: the same ticks (announcements, unlocks, DVOL, liquidations, taker, OI, efficacy, calls, scanner, book, funding refresh), then the per-coin calculation |
| Paper trades | freqtrade dry trades: probes and `t_*` test trades (barrier stop, time exit) | dropped (D1) |
| Telegram commands | `BTCGateCommands` thread | unchanged, runs in the worker |

**The key change is in the BTCGate repo, not NFIForge:** the per-coin logic now inside the freqtrade strategy
(indicators, fast flags, footprint, risk, ledger signal, announcement shorts, scanner, commands) moves into the
`btcgate` package as a plain engine with no freqtrade in it. BTCGateMonitor becomes a thin freqtrade wrapper around
that engine, and NFIForge's worker becomes a second thin wrapper. Both then run identical code. This is a BTCGate
release on its own, checked by replaying the same candles through old and new code (zero differences) before anything
else is built.

## 5. Settings (BTCGate tab, admin edits, viewers read)

- One switch per module, from BTCGate's own settings: trend, turbulence (+ rolling), fast volume, fast OI, fast
  direction, footprint / forced, DVOL, calendar (FOMC, US open), unlocks, announcements (+ hack locks), risk
  probability, book, scanner, calls, efficacy, HL archive, ledger signals.
- Dependencies shown, not hidden: risk probability greys out with "needs fast volume, DVOL and US open" when one is off.
- Changes are written to the worker's `btcgate.json` and the worker restarts itself (about 1 min with the candle
  cache). No NFIForge restart.
- **Alerts:** each alert type (lock, unlock, turbulence HIGH, fast flags, catch-up, absorb, book swing, scanner, paper
  short) has two switches: **phone push** (NFIForge's) and **Telegram** (BTCGate's bot). Telegram token and chat id set
  here, stored in the secret file, never shown again.

## 6. Pages: one "BTCGate" menu entry, tabs

| Tab | Content |
|---|---|
| Market | BTC trend and risk regime, DVOL and jump, FOMC / US open, coins with fast flags on right now |
| Coins | every watched coin: turbulence, risk %, trend, lock (why), unlock countdown, buyback %/yr, fast flags; sortable, search; scanner picks marked |
| Signals | catch-up / absorb / forced / contested alerts with their 1 h, 4 h, 24 h result against the same coins' usual move, and the ledger's signals, newest first |
| Ledger | each tag vs random by market day, days counted vs the 20 needed, review dates, outcome rules |
| Scanner | flagged now (pump, volatile, slow pump / bleed, approaching your bots' lists) with what followed such moves; recovery list from the bots' blacklists |
| Book | per bot: open trades as independent bets, likely 24 h swing, crash line, 30 day history; optional alerts |
| Settings | section 5 |

Into existing pages: Positions gets badges per trade (locked, unlock in N d, turbulence HIGH, risk %); BTCGate alerts
go into the event stream and notifications like any other alert.

## 7. Moving off nexusforge

1. BTCGate engine release (section 4), deployed to nexusforge first: same signals, only the code moved. Needs your
   approval (NFI folder write + nexusforge restart), as every BTCGate deploy does.
2. NFIForge worker runs **alongside** nexusforge with its own fresh data folder. Daily comparison of the two signal
   tables; target: identical signals on identical candles, coin list differences explained.
3. After the 8 Nov ledger review, and once parity holds: copy nexusforge's databases (with `-wal`) into NFIForge's data
   folder, start the worker on them, stop nexusforge. The ledger continues; if parity didn't hold, the clock restarts
   (the v2.20 rule).

## 8. Build steps

| Step | Content |
|---|---|
| BTCGate 2.x | engine out of the strategy, parity replay, no behaviour change |
| 1 | master switch, supervisor, worker (coin list, candles, loop), read-only Market / Coins / Ledger tabs |
| 2 | module settings, alerts to push + Telegram, Positions badges, event stream |
| 3 | coin list setting (D2), open-trade coins always watched |
| 4 | Signals tab: alerts with their 1 h / 4 h / 24 h result vs the same coins' usual move, ledger signals |
| 5 | Book tab, Scanner tab (BTCGate 2.38: scan / recovery as data), own Telegram bot and commands |

Parity note: on nexusforge the `core64` and `breakdown` ledger tags are calculated on the bot's own (Bybit) 5m, 1h and
4h candles; the worker uses Binance's. Those two tags will differ between the two, so their ledger can't simply continue
on the worker; the other tags and the labels use Binance data on both.

## 9. Decisions (user, 2026-10-10)

- **D1 paper trades: dropped.** No probes or `t_*` dry trades; the ledger scores every signal from the signals table.
- **D2 coin list: a setting with two choices.**
  - *Full* (default): nexusforge's filters exactly (Binance futures, volume / age / price / spread / range
    stability, ~150 coins). Needed for the side-by-side parity run and for the ledger, whose random control is drawn
    from this universe.
  - *Bots' coins*: the union of the connected bots' whitelists (read from their API) plus BTC, mapped to Binance
    symbols (e.g. 1000-prefixed coins). Lighter, and covers exactly what the bots can trade. Coins with no Binance
    perpetual show "no data". The ledger pauses in this mode (different universe = not comparable).
  - Both modes add the coin of every open trade (NFIForge shares the bots' whitelists and open trades with the
    worker in `bot_coins.json`, checked every 30 s), so a position outside the list still gets labels. Those extra
    coins also enter the ledger in Full mode; each coin adds its own signals and random draws, so the comparison
    stays like for like.
- **D3 data: Binance**, whatever exchange the bots use (the research and pass bars are on Binance data).
