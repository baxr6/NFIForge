# NFIForge design

A self-hosted, real-time dashboard for [freqtrade](https://www.freqtrade.io/) bots, with extras for
[NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity) (NFI). Works with any freqtrade strategy;
the NFI bits show up when an NFI strategy is detected.

---

## 1. Goals and non-goals

**Goals**
- One screen that answers "is everything OK and what is my money doing" for one or many bots, live.
- Setup in a few minutes for someone already running freqtrade in Docker.
- Safe to point at a real-money bot: read-only unless trade actions are switched on for that bot, and then every
  action on a live bot needs the coin typed back.
- Show what an NFI user otherwise looks for across FreqUI, Telegram and the logs (grinding, de-risk, abandon, tags).
- Python backend and Vue 3 frontend, the same languages freqtrade and FreqUI use.
- Charts that look like a trading terminal, not plain defaults.

**Non-goals**
- Not a FreqUI replacement for configuring bots.
- Changes nothing on a bot unless trade actions are switched on (`write_actions` + the bot's `trading`): then admins
  can force entries, adds and exits, cancel, reload and delete trades, and pause, start, stop or reload the bot.
- No exchange API keys. Exchange data comes from public endpoints only.
- No cloud service, cloud accounts or telemetry (sign-in uses NFIForge's own local accounts).

---

## 2. Architecture

```
 Browser (Vue 3 app)
    │  HTTP + one WebSocket (/ws)
    ▼
 NFIForge backend (FastAPI, one container)
    ├─ BotConnector (one per bot) ── REST polling ──────────► freqtrade api_server (/api/v1/...)
    │                              ├─ message WebSocket ───► freqtrade /api/v1/message/ws
    │                              └─ trade actions (opt-in) ► /forceenter, /forceexit, /trades/{id}/...
    ├─ CandleSource (ccxt, public REST) ────────────────────► exchange candles and live prices
    ├─ HostMonitor (psutil) ─────────────────────────────────► host cpu / ram / disk / network
    │  └─ ContainerMonitor ── cgroup files + /proc (ro) ────► per-container memory, cpu, restarts
    ├─ Notifier ── alert rules every 15 s, trade events from the bots' streams
    ├─ Store (SQLite, own file) ── equity, notifications, server history
    └─ Hub ── pushes state changes to the browsers
```

- **One container**: the Vue app is built into the image and served by FastAPI. No Node.js needed to run it.
- **Push to the browser**: the backend holds the state and pushes changes over one WebSocket, however many panels
  are open.
- **Light on the bots**: freqtrade is polled sparingly (§7) and its own message WebSocket gives fills and exits as
  they happen.

---

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11+, FastAPI, uvicorn, httpx, websockets, pydantic | freqtrade users already know Python; async handles many bots in one process |
| Exchange data | ccxt (public REST) | Same library freqtrade uses; every exchange freqtrade supports |
| Host stats | psutil; kernel cgroup files for containers | No agent, no Docker socket |
| Storage | SQLite (WAL), own file under `/data` | Zero setup; never writes to freqtrade's database |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Tailwind CSS | Same stack as FreqUI |
| Charts | lightweight-charts v5 (candles, equity), ECharts (heatmaps, calendar, bars, lines) | Canvas, fast with many live points, full control over the look |
| Layout | grid-layout-plus | Drag / resize / hide panels, saved per page |
| Packaging | Docker image (amd64 + arm64) and `install.sh`; a pipx wheel on every release | Matches how freqtrade is usually run; pipx for bots run from a venv |
| Licence | MIT | Talks to freqtrade only over its API |

---

## 4. Setup

`./install.sh` checks Docker, asks how NFIForge reaches the bots (same machine or a Docker network), the dashboard
port, who may open it (this machine, this machine + Tailscale, or the whole network), then each bot's api url,
username and password. Every login is tested before saving. It writes `config.yaml`, an owner-only `.env` for the
passwords and a `docker-compose.yml`, starts the container and asks for the first admin account.

Without Docker: `pipx install` the wheel from a release, then `nfiforge init` asks the same questions, writes
`~/.config/nfiforge/config.yaml` (owner-only) and can install a systemd user service.

```yaml
# ~/nfiforge/config.yaml (written by install.sh)
host: 127.0.0.1                # or a list, e.g. [127.0.0.1, 100.x.y.z] for tailscale
port: 8880
data_dir: /data
write_actions: false           # trade actions off for every bot unless true
bot_editing: local             # add / edit / remove bots in the ui: local, network, off
bots:
  - name: "Live"
    url: http://127.0.0.1:8080
    username: freqtrader
    password_env: NFIFORGE_PW_1   # the password itself is in .env
    trading: false              # this bot's own trade-actions switch
```

- `./install.sh --update`: backs up config and data, updates, rebuilds, restarts; the old version comes back if it
  fails.
- `./install.sh --add-bot`, or **Manage Bots** in the dashboard: add a bot without touching the files.
- The container is read-only with all capabilities dropped; of the host it sees only `/proc`, `/sys/fs/cgroup` and
  one file on the root disk (for its size), all read-only, mounted under `/host`.

---

## 5. Data sources

| Need | Source | When |
|---|---|---|
| Open trades, P&L, orders, liquidation price | `GET /status` | every 5 s |
| Closed trades | `GET /trades` | full sync at start, then the newest every minute |
| Profit, drawdown | `GET /profit` | every 60 s |
| Balance | `GET /balance` | every 15 s; equity snapshots kept (freqtrade keeps no equity history) |
| Last loop | `GET /health` | every 5 s; loop time from consecutive `last_process` |
| Config, version | `GET /show_config`, `/version` | at connect, config again every 60 s |
| Whitelist, blacklist, locks | `GET /whitelist`, `/blacklist`, `/locks` | 60 s / 5 min / 60 s + websocket `whitelist` |
| Live events | `WS /api/v1/message/ws`: fills, exits, cancels, protection locks, warnings, new candles | instant |
| Bot's candles + indicator columns | `POST /pair_candles` with `columns` (`GET` on older freqtrade) | on demand |
| Strategy plot config | `GET /plot_config` | on demand |
| NFI grind state | `GET /trades/open/custom-data` | every 30 s |
| Signal radar (per bot, opt-in) | `POST /pair_candles` with the signal and guard columns, every whitelisted pair | 24 h once, then the last 3 candles after each new candle |
| Logs | `GET /logs` (freqtrade keeps its last 1000 lines) | every 3 s, kept since start |
| Exchange candles | ccxt public REST | on demand, cached |
| Live price (trade forms) | ccxt public ticker | every 3 s while a trade form is open, shared for 2 s |
| Best / worst move of closed trades | ccxt candles over each trade's life (1m up to 16 h, then 15m to 1d) | once per trade in the background, ~2 a second, kept |
| Host + containers | psutil, cgroup files and `/proc` through the read-only `/host` mounts | every 5 s / 10 s |

---

## 6. Pages

**LIVE**
- **Trading** (home): one tab per bot. Status strip (bot, exchange, data, server, risk), money row, gauges, a card per
  slot (pair, side, leverage, NFI mode, P&L, mini chart, liquidation distance, grind adds), today's P&L, BTC market
  pulse, event stream. Panels can be moved, resized and hidden.
- **Positions**: every open trade of every bot, sortable (incl. average entry, live price and grind levels used), with the trade
  inspector (incl. the ladder: margin in / out per grind level); **+ new entry** and the
  inspector's actions (add, exit, cancel, reload, delete) when trade actions are on.
- **Chart**: the bot's own candles with any of its indicator columns (defaults from the strategy's plot config), or
  15m to 1d candles from the exchange; every trade on the pair marked, the open one with average entry, liquidation
  and profit zone. **+ entry** / **+ add** for the shown pair when trade actions are on.
- **Risk & exposure** (Trading panel): margin used, real leverage, trades near liquidation, and a move table (every
  coin ±5 to 30 %: open P&L change, share of equity, which trades liquidate). From `/status` and `/balance` only.
- **Signal Radar** (bots with radar on): guard summary, a pairs × candles grid (traded / blocked / not taken / guard
  off) and the latest signals with what happened to each; blocked reasons from trades, slots, locks and NFI's
  "Cancelling entry" log lines.
- **Logs**: newest first, level / text / kind filters, repeated lines grouped, pairs link to the chart.
- **Notifications**: open alerts on top, then alerts, trade events and trade actions (who, what was sent, the bot's
  answer) newest first; unread count in the menu.

**STATISTICS**
- **Trade History**: closed trades with filters and the trade inspector (summary, MFE / MAE, chart, orders, same-tag
  stats, NFI custom data).
- **Analytics**: profit over time, daily calendar, breakdown by tag / exit / pair / weekday / hour / time held, tag ×
  exit heatmap, all with 95 % ranges; funding card; drawdown under the profit curve (deepest, longest under
  water, now, in quote or % of the account at its high); best / worst move (MFE / MAE) vs result scatter.
- **Pairs**: find a pair (in a trade, whitelisted, locked, blacklisted by which rule, filtered out and why),
  whitelist, locks, blacklist rules, whitelist changes. Lock / unlock (`POST /locks`, `DELETE /locks/{id}`) and blacklist
  add / remove (`POST` / `DELETE /blacklist`) under the trade-action switches.
- **Timeline** (Trade History panel): events, equity, open slots, server CPU and loop time for one bot on one shared,
  zoomable time axis; from the equity, server history, notifications and trade history nfiforge already keeps.

**SYSTEM**
- **Server**: host gauges, every container's memory against its limit, cpu, out-of-memory kills, uptime and
  restarts; history of cpu, ram, disk, container memory and bot loop time.
- **Manage Bots**: the bots NFIForge watches; add / edit / remove with a login test, live, no restart, and each ui
  bot's trade-actions switch. Bots from `config.yaml` are listed but locked. Changes only from this machine unless `bot_editing: network`.
- **Bot Health**: per bot, bot control (pause, start, stop, reload config) when allowed, then checks worst first (api, live stream, running, last loop, real money, margin mode,
  stoploss on exchange, force entry, locks, debug logging, newer freqtrade) and the settings that matter.
- **Settings**: timezone, trading day, alert levels, desktop pop-ups, gauges.

---

## 7. Backend

**Modules**
- `connectors/freqtrade.py`: BotConnector: JWT login and refresh, REST pollers, message websocket with reconnect, log
  lines kept since start, whitelist changes.
- `connectors/market.py`: exchange candles and live prices through ccxt, cached.
- `connectors/host.py`, `connectors/containers.py`: host and per-container stats. Containers are read from the
  kernel's cgroup files and the host process table; labels use only safe parts of the command line (program,
  freqtrade subcommand, strategy, config name), never the full line.
- `health.py`: bot health checks. `alerts.py`: alert rules and trade events kept as notifications.
- `excursions.py`: background worker measuring each closed trade's best and worst move, kept in the store.
- `radar.py`: signal radar rows per pair and candle, and each signal's outcome.
- `store.py`: SQLite; schema changes in an ordered list, upgraded in place.
- `settings.py`, `uibots.py` (bots added in the ui), `updates.py`, `hub.py`, `app.py` (routes).

**Browser API**
- `GET /api/bots`, `/api/bots/{name}/state`, `/history`, `/candles`, `/ticker`, `/frame`, `/logs`, `/pairs`,
  `/checks`, `/excursions`, `/radar`, `/api/host`, `/api/server/history`, `/api/notifications`, `/api/settings`, `/api/manage/bots`.
- `/api/auth/*` (sign in / out, password, phone pairing) and `/api/users` (admins).
- `/api/fx/{currency}`: USDT in a real currency from a direct USDT market (Kraken mid, BTC Markets backup for AUD),
  cached a minute, none when older than 5 minutes. Display only.
- `/api/push/key | subscribe | unsubscribe | test`: phone alerts (web push) for the signed-in user's device.
- `WS /ws` pushes `{type, bot, data}`: `snapshot`, `state_diff`, `event`, `host`, `notification`, `settings`.
- Trade actions, the only routes that change a bot: `POST /api/trade/{bot}/enter | exit | cancel | reload | delete`
  and `/control` (pause, start, stop, reload_config; a live bot needs its name typed back).
  Admins only; refused unless `write_actions` and the bot's `trading` are on; the bot's `dry_run` is asked fresh and a
  live bot needs the coin typed back; sent once over a fresh connection, never retried; an add needs a stake
  (freqtrade would otherwise use a whole new trade's stake); every action is logged as a notification.

**Poll budget per bot**: `/status` 5 s, `/health` 5 s, `/balance` 15 s, `/profit` 60 s, `/whitelist` 60 s, config and
locks 60 s, custom data 30 s, logs 3 s, newest closed trades 60 s. Everything else on demand.

---

## 8. Look

Colours come from FreqForge (`static/css/app.css`) so the two tools look like one family, defined once as CSS
variables and used through Tailwind.

| Token | Hex | Use |
|---|---|---|
| `--void` | `#0a0e13` | page background |
| `--panel` / `--panel-raised` / `--panel-hover` | `#12181f` / `#181f28` / `#1c2430` | panels, cards, hover |
| `--line` / `--line-bright` | `#242e3b` / `#334155` | borders, grid lines |
| `--text` / `--text-dim` / `--text-faint` | `#e4eaf1` / `#8695a7` / `#4e5a6b` | text levels |
| `--green` / `--amber` / `--red` | `#3ddc84` / `#f0a83c` / `#f0566a` | profit / warning / loss |
| `--brand-a` → `--brand-b` | `#8b5cf6` → `#3ea1ff` | logo, active page, equity gradient |

- IBM Plex Sans for text, IBM Plex Mono for every number so digits line up. Bundled, no font requests.
- Status is never colour alone: always an icon, sign or word too.
- Charts: transparent canvas, faint horizontal grid only, 2 px lines with a gradient fill, pulsing live end, floating
  OHLC readout instead of a tooltip box. Candles 90 % opacity, volume in its own pane. Trade marks: entry ▲, exit ▼,
  grind adds as dots sized by stake, average entry dashed, liquidation solid red.
- Gauges are our own SVG: analog (chrome bezel, red needle with spring movement, warn / danger arcs) or digital
  (segment arc with a glowing readout), chosen per gauge in Settings.

---

## 9. NFI extras

| What | How |
|---|---|
| Mode of a trade (normal, pump, quick, rebuy, rapid, grind, top coins, scalp) | Map of NFI entry tags to modes |
| Grind adds and partial exits | Order tags from `/status` and closed trades |
| Grind state | `/trades/open/custom-data` |
| Exit types | NFI exit reasons grouped (`exit_long_rebuy_d_3_100` → `exit_long_rebuy`) for charts and tables |
| Indicators and protections on the chart | Any column of NFI's dataframe via `/pair_candles` |

---

## 10. Security

- Binds `127.0.0.1` by default. Everyone signs in (admin or viewer); passwords are scrypt hashes, sessions HttpOnly
  cookies of which only a hash is stored; failed sign-ins are rate limited.
- Bot passwords come from `.env` (or `bots.json` for bots added in the ui, owner-only); never sent to the browser,
  never logged. API tokens that show up in bot log lines are masked.
- Read-only towards the bots unless trade actions are on; live bots need the coin typed back, every action is logged.
  Adding or removing bots is local-only by default (`bot_editing`).
- Host mounts are read-only and limited to `/proc`, `/sys/fs/cgroup` and one disk probe. No Docker socket: even
  mounted read-only it would give full control of Docker.
- Outbound calls only to the configured bots, public exchange endpoints, GitHub's release check (can be turned off
  with `update_check: false`) and, for devices that turned phone alerts on, the browsers' push services. A push
  address is only accepted on those services' hosts (Apple, Google, Mozilla, Microsoft), so a subscription can't
  point the server anywhere else; messages are encrypted for the device (RFC 8291) and signed with `vapid.pem`.
- Viewers can be limited to some bots, some pages or a percent-only view; share links open a percent-only page
  without an account. Both checked on the server ([SHARING.md](SHARING.md)).

---

## 11. Quality

- Backend tests (pytest) against a fake freqtrade server: login, polling, websocket, candles, logs, pairs, health
  checks, alerts, container stats from a fake host folder, bot management, accounts and phone pairing, trade
  actions and bot control (switches, live confirmation, logging, refused input), live price, MFE / MAE measuring,
  phone push (encryption checked against the RFC 8291 example, signing, refused push addresses).
- ruff for lint and formatting; vue-tsc type check on every frontend build.
- CI runs the tests and builds the image; a `v*` tag that matches the code version publishes the release and the
  multi-arch image.

---

## 12. Not built yet

- Nothing planned. Grind-level exits were dropped: freqtrade tags every manual exit `force_exit`, so they would need a
  freqtrade change.
