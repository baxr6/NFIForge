# NFIForge help

NFIForge is a dashboard for Freqtrade bots, with extras for NostalgiaForInfinity (NFI) and an optional BTCGate market
monitor. This guide covers everyday use. Install details are in the [README](../README.md) and every change is in the
[CHANGELOG](../CHANGELOG.md).

The same guide is in the app under **Help**.

## Contents

1. [Getting started](#getting-started)
2. [Accounts](#accounts)
3. [Bots](#bots)
4. [Phones](#phones)
5. [Pages](#pages)
6. [Trade actions and bot control](#trade-actions-and-bot-control)
7. [Alerts and notifications](#alerts-and-notifications)
8. [Settings](#settings)
9. [NFI extras](#nfi-extras)
10. [BTCGate](#btcgate)
11. [Updating](#updating)
12. [Data and backups](#data-and-backups)
13. [Troubleshooting](#troubleshooting)
14. [Questions](#questions)

## Getting started

NFIForge talks to each bot through Freqtrade's REST API, the same one FreqUI uses. Each bot needs `api_server`
enabled in its config, with a username and password.

There are two ways to install:

| way | for | command |
|---|---|---|
| Docker | bots run in Docker | `./install.sh` from the repository |
| pipx | bots run from a Python venv, or no Docker | `pipx install ./nfiforge-*.whl`, then `nfiforge init` |

Both ask the same questions:

- the dashboard port (8880 by default)
- who may open it: this computer, this computer plus Tailscale, or the whole network
- each bot's API address, username and password, tested before saving
- the first admin account

Then open `http://127.0.0.1:8880` and sign in.

With pipx, `init` offers to run NFIForge as a systemd user service, so it starts at every boot.

| task | command |
|---|---|
| status | `nfiforge service status` |
| logs | `journalctl --user -u nfiforge -f` |
| restart | `systemctl --user restart nfiforge` |

## Accounts

Everyone signs in with a username and password.

| role | can |
|---|---|
| admin | everything: settings, page layouts, bots, trade actions (when switched on) |
| viewer | look, change nothing; by default everything, or what the admin allows (below) |

**What a viewer sees** (Settings → Users → the "Sees" column): the admin picks

- **bots**: all, or some. The others are left out everywhere, live updates and alerts included.
- **pages with their own data**: Signal Radar, Order Flow, BTCGate, Logs, Server, Notifications. Trading, Positions,
  Chart, Trade History, Analytics, Pairs and Bot Health read the same bot data, so they come with the bots.
- **percent view only**: the viewer gets one page with their bots' results in percent (as a share link shows them,
  below), and no amounts anywhere.

The server checks this on every request; changes apply straight away (an open page within 30 s).

**Share links** (Settings → Share links, admins): a page anyone with the link can open without an account, showing
the chosen bots' results in percent only: profit % today / 7 d / 30 d / all, open trades now, win rate, profit
factor, deepest drawdown, slots, a growth line from 100 and a daily calendar; optionally the open trades, the last 50
closed trades, entry tags / exit reasons and the bot names. No balances, stake, amounts or prices. The link is shown
once when made (only a hash is kept), can expire, and can be revoked at once; the list shows how often each was
opened. NFIForge has to be reachable for the people you send it to (a reverse proxy or tunnel); it opens nothing by
itself.

- **Add a user:** Settings → Users, or `nfiforge user add NAME --role viewer`. With Docker, run it inside the container
  or use `./install.sh --add-user`.
- **Change your password or sign out every device:** Settings → Account.
- **Forgotten admin password:** `nfiforge user password NAME` on the server.

Sign-ins last 30 days. After 5 failed sign-ins from one address in 5 minutes, that address has to wait.

## Bots

**Add a bot:** Manage Bots → **+ add bot**. Enter the name, API address, username and password, press **Test**, then
**Add**. The bot shows up straight away, with no restart.

Bots added there can be edited and removed there. Bots from `config.yaml` are listed but locked; change those in the
file. For safety, adding or editing bots only works from the machine NFIForge runs on, because a phone on plain http
would send the password unencrypted. `bot_editing: network` in `config.yaml` allows it from other devices, and
`bot_editing: off` turns it off.

From the command line: `./install.sh --add-bot` (Docker), or add an entry under `bots:` in `config.yaml` and restart.

Each bot has these settings in Manage Bots → edit (or in `config.yaml`):

| switch | what it allows |
|---|---|
| Allow trade actions and bot control (`trading`) | trades, bot control, locks and blacklist from NFIForge; also needs `write_actions: true` |
| Signal radar (`radar`) | the Signal Radar page for this bot |
| Name, address and login | how NFIForge reaches the bot |
| Docker container (`container`, optional) | shown on the Bot card, so you know what to `docker restart` |

## Phones

**Open it on a phone.** NFIForge must be reachable from the phone. Tailscale is recommended: it is encrypted and works
away from home. To sign a phone in without typing a password:

```bash
nfiforge pair NAME --link        # pipx
./install.sh --phone             # Docker
```

This prints a link, and a QR code if `qrencode` is installed. The link works once, for 10 minutes.

**Add to the home screen.** In the browser's share menu, choose **Add to Home Screen**. NFIForge then opens like an
app.

**Bottom tab bar.** On screens narrower than 1024 px, a bar at the bottom has Trading, Positions, BTCGate, Alerts (with
the unread count) and **More** for every other page.

**Push alerts.** Push sends alerts to the phone with the app closed. It needs https, which Tailscale gives for free:

1. In the Tailscale admin console, **DNS → HTTPS Certificates → Enable** (once per tailnet).
2. On the server, run `sudo tailscale serve --bg 8880`. If port 443 is already used, run
   `sudo tailscale serve --bg --https=8443 8880` and add `:8443` to the address.
3. Open `https://<server>.<tailnet>.ts.net` on the phone. On an iPhone, add it to the home screen and open it from
   there (iOS only allows push for home screen apps).
4. Go to **Settings → Phone alerts → Alerts on this device**, then **Send a test**.

Each device turns push on for itself, and signing the device out stops it. Push carries alerts only, not every trade
event.

## Pages

### Live

**Trading** is the home page, with one tab per bot. It shows:

- a status strip: bot, exchange, data, server and risk
- the money row and gauges
- a card per slot: pair, side, leverage, NFI mode, P&L, mini chart, distance to liquidation and grind adds
- today's P&L, the BTC pulse and the event stream

Admins can move, resize and hide panels with the layout button; the layout is the same for everyone. On a phone, open
trades come first and empty slots fold into one line.

**Positions** lists every open trade of every bot, sortable by any column. Tap a trade for the **trade inspector**:
chart, orders, grind ladder, best and worst move (MFE / MAE) and NFI custom data. With BTCGate on, each trade gets
[badges](#badges-on-positions). With trade actions on, **+ new entry** opens a trade and the inspector can add, exit,
cancel, reload or delete.

**Chart** shows the bot's own candles with any indicator column the strategy calculates, or 15m to 1d candles straight
from the exchange. Every trade on the pair is marked. The open trade shows its average entry, liquidation price and
profit zone.

**Signal Radar** answers "why didn't the bot take that move?" For every whitelisted pair it shows the strategy's entry
signals per candle over the last 7 days (pick 1h to 7d), and what happened to each:

| result | meaning |
|---|---|
| traded | a trade was opened |
| blocked | something stopped it: already in a trade on that pair, slots full, pair locked, the reason NFI logged, not enough balance, or the order never filled |
| not taken | no reason was found |

The radar is off by default for each bot; turn it on in Manage Bots → edit → Signal radar. It reads the bot's last 3
candles of every pair after each new candle (about 2 s for 100 pairs). Check the bot's loop time on **Server** after
turning it on. Signals and the log lines that explain them are saved, so a restart keeps the 7 days; the first sweep
after turning it on fills in as much as the bot's own chart data still holds.

**BTCGate** is described under [BTCGate](#btcgate).

**Logs** shows the bots' logs, newest first. You can filter by level, text and kind, and repeated lines are grouped.
Pairs link to the chart. Freqtrade's API only keeps its last 1,000 lines, so NFIForge keeps its own copy from when it
started. A bot running with `-v` (debug) produces lines faster than that copy can catch, and the page says so.

**Notifications** lists open alerts first, then alerts, trade events and trade actions, newest first. The unread count
shows in the menu. See [Alerts and notifications](#alerts-and-notifications).

### Statistics

**Trade History** lists closed trades with filters and the same trade inspector, plus same-tag stats. **↓ download**
saves the filtered trades as CSV, or as Excel with a second sheet holding every order of those trades. Positions, the
Analytics breakdown (Excel: every breakdown, one sheet each) and the inspector's orders have the same button. Times
are in the time zone set in Settings, named in the column header; with a display currency set, money columns get a
second column in it at today's rate. The
**Timeline** panel puts equity, events, open slots, server CPU and loop time on one zoomable time axis (6 h to 30 d).

**Analytics** covers:

- profit over time and a daily calendar
- breakdown by tag, exit, pair, weekday, hour and time held, and a tag × exit heatmap, all with 95 % ranges
- funding over any range
- drawdown: deepest, longest under water and now
- a best / worst move (MFE / MAE) vs result scatter

The 95 % ranges show how sure a number is: a wide range means too few trades to tell.

**Pairs** answers "why is the bot (not) trading this coin?" Search a pair to see whether it is in a trade,
whitelisted, locked, blacklisted (by which rule) or filtered out (and why). With trade actions on, you can lock and
unlock pairs and edit the blacklist here.

### System

**Server** shows host memory, CPU and disk, and every container's memory against its limit, CPU, out-of-memory kills,
uptime and restarts, with history. NFIForge has no Docker socket and reads only what the host shows it.

**Manage Bots** is where bots are added, edited and removed. Admins only.

**Bot Health** checks each bot, worst first: API, live stream, running, last loop, real money, margin mode, stoploss on
exchange, force entry, locks, debug logging and a newer Freqtrade. With bot control allowed, it also has pause,
start, stop and reload config.

**Settings**: see [Settings](#settings).

**Help** is this guide.

## Trade actions and bot control

Trade actions are **off by default** and need two switches:

1. `write_actions: true` in `config.yaml`. This is file only, so a signed-in browser can't turn it on.
2. The bot's own switch: Manage Bots → edit → **Allow trade actions and bot control**, or `trading: true` under the bot
   in `config.yaml`.

Once both are on, admins can:

| action | where |
|---|---|
| open a trade | Positions → **+ new entry**, Chart → **+ entry** |
| add to a trade, exit all or part, cancel the open order, reload from the exchange, delete | the trade inspector |
| pause entries, start, stop, reload config | Bot Health, or **control** on the Trading page's bot card |
| lock or unlock a pair (or `*` for all), on one side or both | Pairs → Locks |
| add or remove blacklist entries | Pairs → Blacklist |

Safety rules:

- Every action shows what will be sent before it goes.
- On a **live bot** (`dry_run: false`, checked fresh each time) you type the coin, or the bot's name, to confirm.
- Actions are sent once and never retried.
- Every action is logged under **Notifications → actions** with who sent it and the bot's answer.
- The entry, add and exit forms show the live price, bid and ask every 3 s. **use** puts the ask (buying) or bid
  (selling) in the limit price, and a warning shows when a limit would fill straight away.

Things to know:

- **Pause** stops new entries but still manages open trades. **Stop** stops managing open trades too.
- A blacklist edit lasts until the bot restarts or reloads its config. To keep it, add it to the bot's config.
- On NFI bots, an add can be given a grind level, so NFI counts it in that level and sells it at that level's target.
  Exits can't pick a grind level, because Freqtrade tags every manual exit `force_exit`.

## Alerts and notifications

NFIForge checks every bot and the server and raises an alert when something needs attention. The levels are set on
**Settings → Alerts**:

| alert | when (default) |
|---|---|
| bot API down | the bot doesn't answer for 60 s |
| bot not running | the bot is stopped or paused |
| bot stuck | no bot loop for 10 minutes |
| live stream down | fills and exits arrive late |
| close to liquidation | an open trade within 15 % of its liquidation price |
| drawdown | the bot's current drawdown above 10 % |
| disk full | server disk above 90 % |
| RAM | server RAM above 92 % |
| container memory | a container above 90 % of its memory limit |
| container killed or restarted | an out-of-memory kill or a restart |

With BTCGate on, its alerts (forced dump, forced squeeze, catch-up, lock, scanner, book) join the list under their own
filter.

Alerts can reach you three ways:

- the **Notifications** page and the unread count
- **desktop pop-ups** while a tab is open (Settings → Alerts)
- **phone push** (see [Phones](#phones))

**Keep trade events** (Settings → Alerts) also stores fills, cancels, protections and warnings from the bots.

## Settings

Settings are saved on the server automatically and are the same on every device. Viewers can see them but not change
them.

| section | what it holds |
|---|---|
| Account | your password; sign out every device |
| Phone alerts | push on this device, test message |
| Users | add, remove and change role (admins) |
| General | local time zone, when the trading day starts, display currency (AUD, USD, EUR, GBP, CAD, CHF, JPY, at the live USDT rate; display only) |
| Alerts | the alert levels above, keep trade events, desktop pop-ups |
| Gauges | which gauges the Trading page shows |

Some settings live only in `config.yaml` and need a restart:

| key | meaning |
|---|---|
| `host`, `port` | where the dashboard listens. `127.0.0.1` is this computer only; add a Tailscale address for phones |
| `write_actions` | master switch for trade actions |
| `bot_editing` | `local`, `network` or `off` |
| `update_check` | `false` hides the "new version" note |
| `btcgate` | `enabled`, `memory_mb` |
| `bots` | bots defined in the file |

## NFI extras

NFIForge reads NFI's entry tags, order tags and custom data:

| what | where it shows |
|---|---|
| trade mode (normal, pump, quick, rebuy, rapid, grind, top coins, scalp) | slot cards, Positions, Analytics |
| grind adds and partial exits | slot cards, the inspector's grind ladder (margin in and out per level) |
| grind state | the inspector's NFI custom data |
| exit types, grouped (`exit_long_rebuy_d_3_100` → `exit_long_rebuy`) | Analytics, Trade History |
| any dataframe column, such as NFI's protections | Chart |
| why NFI cancelled an entry | Signal Radar |

## BTCGate

BTCGate labels the market for every coin: turbulence, trend, fast volume and open interest spikes, exchange news
locks, token unlocks and the chance of a big move. It also keeps a ledger that scores its signals. It never trades. In
NFIForge it runs as a separate worker on Binance futures data, apart from the bots. It is off by default, and when it
is off nothing of it is loaded.

The full BTCGate guide, including how each label was tested, is in BTCGate's own
[HELP](https://github.com/baxr6/BTCGate/blob/main/docs/HELP.md).

### Turning it on

1. Install the package once (pipx installs; it survives NFIForge updates). The exact command, pinned to the right
   BTCGate version, is in the README's BTCGate section.
2. In `config.yaml`, set `btcgate: {enabled: true}`. Optionally set `memory_mb` (default 4096); the worker restarts
   itself if it uses more.
3. Restart NFIForge. **BTCGate** appears in the menu.

The first start loads about 2,500 candles per coin, which takes 5-10 minutes. Later starts take about 15 s. Labels
update 1-2 minutes after each 5 minute candle.

The Docker image doesn't include BTCGate yet.

### Tabs

| tab | what it shows |
|---|---|
| Market | BTC's trend and risk regime, DVOL and its 6 h change, FOMC and US open, how many coins have turbulence HIGH, fast flags or locks, and the signals of the last 24 h |
| Coins | every watched coin: price, turbulence (day and 24 h), trend, big-move risk, lock, unlock countdown, buyback %/yr, fast flags, scanner label and last signal. Sortable and searchable |
| Signals | every alert of the last 7 days with the price then and the move 1 h, 4 h and 24 h later, green when it went the way the alert said. A summary per type compares how often it was right with how often the same coins moved that way anyway. Also the ledger's signals of the last 30 days |
| Scanner | coins flagged now (pump, volatile, slow pump, slow bleed, approaching your bots' lists) with what followed such moves in 2024-26, and the recovery list from your bots' blacklists |
| Ledger | each signal tag against random entries, day by day, with the days counted towards the review |
| Book | each bot's open trades as independent bets: the likely 24 h swing in dollars, a crash line (whole market 10 % / 15 % against the book), the coins carrying most of the risk, and 30 days of history |
| Settings | modules, coin list, alerts, keys (admins edit, viewers read) |

### Reading the labels

| label | values | meaning |
|---|---|---|
| Turbulence | calm / elevated / HIGH | how wild the coin is, daily and over the last 24 h. HIGH days have about 1.5x as many 15 %+ moves. Size, not direction |
| Trend | up / neutral / down | the daily trend; a description, not a forecast |
| Big move risk | % | the chance of a 4 h move at least 3x the coin's usual one. About 11 % is normal |
| Fast volume / fast OI | z-score, flag at 3 | a sudden volume spike, or open interest building fast. A big move is more likely soon, direction unknown |
| Lock | kind | exchange news against the coin: Binance delisting or monitoring tag, Upbit warning, or a hack |
| Unlock | days | a large token unlock (5 %+ of supply) is coming |
| Buyback /yr | % | what the coin's protocol hands holders a year (buybacks, burns or staking payouts) as % of its market cap, from DefiLlama daily. Shown from 1 %. Information only, not tested |

In short: turbulence, risk and fast flags are about **how big** the next move may be, so size down. A lock means **stay
out**. Catch-up is the one tested **direction** lean, and it is small.

### Badges on Positions

Each open trade gets badges from BTCGate:

| badge | meaning |
|---|---|
| locked: … | exchange news against the coin; avoid adding |
| unlock N d | a big token unlock within 7 days |
| turbulence HIGH | the coin is HIGH on the daily or 24 h label |
| move risk N % | big-move risk of 30 % or more |
| a signal name and its age | a BTCGate signal on the coin in the last 24 h |
| not watched | the coin isn't in BTCGate's coin list, so it has no labels |
| no Binance data | Binance has no perpetual for this coin, so BTCGate can't label it |

The coin of every open trade is added to BTCGate's list within a minute, so "not watched" should clear by itself.
Coins match across exchanges, so `1000PEPE` matches `PEPE`.

### Settings tab

- **Modules.** There is one switch per module (labels, fast signals, calendar, news, recording, Telegram). Each says
  what else it needs to do anything.
- **Coin list.**

  | option | coins | signal ledger |
  |---|---|---|
  | Full | about 150 by Binance volume | runs |
  | Bots' coins | only what your bots can trade, plus BTC | pauses; lighter on memory |

- **Alerts.** Per alert type, choose phone push and/or Telegram, and set the coin list and the cooldown.
- **Book.** An optional alert for when the likely swing goes above a dollar limit, or when 6+ trades behave like fewer
  bets than you set.
- **Keys.** The Coinalyze key, Telegram bot token and chat id. They are stored owner-only and only shown as set or not
  set. Without a Coinalyze key, the direction label stays empty. The tab has the steps for making a Telegram bot.

Saving restarts the worker by itself (about 15 s).

### Telegram

With a Telegram bot set up, BTCGate sends the alerts you picked and answers commands from your chat only:

| command | what it does |
|---|---|
| a coin name, or `/coin` | the coin's current reading |
| `/watch`, `/unwatch`, `/watching` | your alert list |
| `/locks` | coins locked now |
| `/scan` | coins flagged now, using your bots' whitelists |
| `/recovery` | coins on your bots' blacklists that look tradable again |
| `/book` | the book of each bot NFIForge is connected to |
| `/call`, `/close`, `/calls`, `/callstats` | log and score your own trade ideas |
| `/version`, `/help` | version and command list |

## Updating

| install | update |
|---|---|
| Docker | `./install.sh --update`: backs up config and data to `~/nfiforge/backups/<date>-v<old>`, rebuilds, restarts, and puts the old version back if anything fails |
| pipx | download the new wheel (`gh release download -R baxr6/NFIForge -p '*.whl'`), `pipx install --force ./nfiforge-*.whl`, then `systemctl --user restart nfiforge` |

The sidebar shows a note when a newer release is out. The BTCGate package installed with `pipx inject` stays through
NFIForge updates. When a release needs a newer BTCGate, the changelog says so.

## Data and backups

| install | config | data |
|---|---|---|
| pipx | `~/.config/nfiforge/config.yaml` | `~/.local/share/nfiforge/` |
| Docker | `~/nfiforge/config.yaml` and `.env` | `~/nfiforge/data/` (backups in `~/nfiforge/backups/`) |

The data folder holds:

| file | contents |
|---|---|
| `nfiforge.db` | accounts and sessions, notifications and actions, equity, server and loop-time history, MFE / MAE results, push subscriptions |
| `settings.json` | the Settings page |
| `bots.json` | bots added in Manage Bots, with their logins |
| `vapid.pem` | the push signing key; losing it means every phone has to turn push on again |
| `btcgate/` | BTCGate's settings, keys, databases and worker log |

`config.yaml`, `.env`, `bots.json` and `btcgate/btcgate_secret.json` hold passwords and keys: keep them owner-only and
out of git.

SQLite databases are in WAL mode. To back one up while NFIForge runs, copy its `-wal` and `-shm` files with it, or stop
NFIForge first.

## Troubleshooting

| problem | what to check |
|---|---|
| Can't open the dashboard from a phone | `host` only allows this computer by default. Re-run the installer, or add the Tailscale address to `host` and restart |
| A bot shows as down | the bot's `api_server` is on, the address is reachable from NFIForge (Docker: same network), and the login is right. Bot Health shows the error |
| Trade action buttons missing | both switches must be on: `write_actions: true` and the bot's `trading` switch, and you must be an admin |
| Adding a bot is greyed out | you're not on the server machine; see `bot_editing` |
| No push on the phone | the page must be on https (Tailscale serve); on iPhone it must be opened from the home screen; then Settings → Phone alerts → Send a test |
| Signal Radar empty | radar is off for that bot (Manage Bots → edit), or no new candle has closed since it was turned on |
| Logs missing lines | the bot runs with `-v`; Freqtrade's API keeps only 1,000 lines |
| BTCGate menu missing | `btcgate.enabled` is false, or NFIForge wasn't restarted |
| BTCGate stuck on loading | the first start takes 5-10 minutes; check `btcgate/worker.log` in the data folder |
| BTCGate restarts by itself | it went above `memory_mb`; raise it or pick the Bots' coins list |
| Badge says not watched | wait a minute (open-trade coins are added automatically); "no Binance data" means it can't be labelled |
| Same BTCGate alert twice | the alert cooldown is kept in memory, so a worker restart can repeat one |
| Service won't start (pipx) | `journalctl --user -u nfiforge -n 50` shows why; often a typo in `config.yaml` |

## Questions

**Can NFIForge trade without me knowing?** No. Nothing is sent to a bot unless `write_actions` is on, the bot's own
switch is on, an admin presses the button and confirms what will be sent. Every action is logged.

**Does it change my bots' configs?** No. Blacklist edits are made through the bot's API and last until the bot reloads.
NFIForge never writes a bot's files.

**Does BTCGate change what my bots do?** No. It labels and alerts; it never blocks, sizes or trades.

**Is it safe to open over my home network?** That option is plain http, so passwords cross the network unencrypted.
Tailscale, or a reverse proxy with https in front of NFIForge, is the safe way.
