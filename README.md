# NFIForge

Real-time dashboard for [freqtrade](https://www.freqtrade.io/) bots, with extras for
[NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity).

What works is below, what changed in [CHANGELOG.md](CHANGELOG.md).

How to use it, page by page: [docs/HELP.md](docs/HELP.md) (also in the app under **Help**).

## Install

### 1. Before you start: turn on each bot's API

NFIForge reads your bots through freqtrade's REST API, the same one FreqUI uses. In each bot's freqtrade config,
`api_server` must be on with a username and password:

```json
"api_server": {
  "enabled": true,
  "listen_ip_address": "0.0.0.0",
  "listen_port": 8080,
  "username": "freqtrader",
  "password": "pick-a-long-password",
  "jwt_secret_key": "pick-another-long-random-string"
}
```

Restart the bot after changing it. If FreqUI already works for that bot, this is done.

Write down for each bot: the address NFIForge will use (for example `http://127.0.0.1:8080`, the port published by
Docker), the username and the password. The installer asks for them.

### 2. Pick a way to install

| your bots run | use | you need |
|---|---|---|
| in Docker | **Docker** (2a) | Docker with the compose plugin, git |
| straight from a Python venv, or no Docker | **pipx** (2b) | Python 3.11 or newer, pipx |

### 2a. Docker

```bash
git clone https://github.com/baxr6/NFIForge.git
cd NFIForge
./install.sh
```

The installer asks, one question at a time:

1. how NFIForge reaches your bots (same machine, or a Docker network)
2. the dashboard port (8880 by default)
3. who may open it: this computer, this computer + Tailscale, or your whole network
4. each bot's api url, username and password (every login is tested before saving)
5. the first admin account (the login for the dashboard itself)

It writes `config.yaml`, an owner-only `.env` for the passwords and a `docker-compose.yml` in `~/nfiforge`, and
starts the container. Keep the `NFIForge` folder: updates run from it.

### 2b. pipx (no Docker)

Download the `.whl` file under **Assets** on https://github.com/baxr6/NFIForge/releases/latest (or, with the GitHub
CLI: `gh release download -R baxr6/NFIForge -p '*.whl'`), then in the folder it was saved to:

```bash
pipx install ./nfiforge-*.whl
nfiforge init
```

`init` asks the same questions as the Docker installer, writes `~/.config/nfiforge/config.yaml` (owner-only: it holds
the bots' api passwords), makes the first admin and offers to start NFIForge now and at every boot as a systemd user
service. Data goes to `~/.local/share/nfiforge`.

- run by hand: `nfiforge` · service: `nfiforge service install | remove | status`, logs `journalctl --user -u nfiforge -f`
- users: Settings → Users, or `nfiforge user add NAME --role viewer`
- phone: `nfiforge pair NAME --link` (link + qr code)

### 3. Open it

Open http://127.0.0.1:8880 (or the port you picked) and sign in with the admin account from the installer. Each bot
shows as a tab at the top. A bot that shows as down: see Troubleshooting in [docs/HELP.md](docs/HELP.md).

## Accounts

Everyone signs in with a username and password. **Admins** change settings, page layouts and bots; **viewers** see
everything but change nothing, or only some bots and pages, or only their results in percent (Settings → Users).
**Share links** (Settings → Share links) show chosen bots' results in percent to anyone with the link, without an
account: no balances or amounts. Add users in **Settings → Users** or with `./install.sh --add-user`; change your own
password or sign out every device in **Settings → Account**. From the command line (inside the container for Docker):
`nfiforge user add|list|password|remove`.
Passwords are stored as scrypt hashes; sessions are HttpOnly cookies (30 days) of which only a hash is stored.

## Add a bot

In the dashboard: **Manage Bots → + add bot** (test the login, then add; it shows up straight away). Bots
added there can be edited or removed there; bots from `config.yaml` are listed but locked. By default this only works
from the machine NFIForge runs on (`bot_editing: network` in `config.yaml` allows it from other devices,
`bot_editing: off` turns it off): from a phone the dashboard is plain http, so a typed password would cross the
network unencrypted.

Or from the command line:

```bash
cd NFIForge && ./install.sh --add-bot
```

Asks for the bot's name, api url, username and password, tests the login, adds it to `config.yaml` and `.env`
(old copies go to `~/nfiforge/backups/<date>-add-bot`) and restarts NFIForge. If NFIForge won't start with the new
bot, the old files are put back. By hand: add an entry under `bots:` in `config.yaml`, its password to `.env` as the
`password_env` name, then `docker compose up -d --force-recreate` in `~/nfiforge`.

## Open it on a phone

```bash
cd NFIForge && ./install.sh --phone
```

Asks which user to sign in as, then prints a link (and a QR code if `qrencode` is installed) that signs a phone or
tablet in without typing a password. The link holds a one-time code: it works once, for 10 minutes. Needs the
dashboard open on Tailscale (recommended: encrypted, and the phone works away from home) or on your network.
When `tailscale serve` forwards to the dashboard (see Phone alerts below), the link uses that https address, so the
phone signs in where it can install the app and get alerts.

On a phone, Positions and Trade History show one card per trade with P&L first; the Trading page puts open trades
near the top, folds the gauges and shows empty slots as one line. Tap a card for the trade inspector.

### Phone alerts (push)

Alerts can reach the phone with the app closed. Push needs the dashboard on https, which Tailscale gives for free:

1. In the Tailscale admin console, **DNS → HTTPS Certificates → Enable** (once per tailnet).
2. On this computer: `sudo tailscale serve --bg 8880` (the dashboard's port). It is then at
   `https://<this computer>.<tailnet>.ts.net`, only on your tailnet. If something else already uses port 443 (a web
   server), use `sudo tailscale serve --bg --https=8443 8880` and add `:8443` to the address.
3. Open that address on the phone. On an iPhone: **Share → Add to Home Screen**, then open NFIForge from the home
   screen (iOS only allows push for apps on the home screen).
4. **Settings → Phone alerts → Alerts on this device**, then **Send a test**.

Each device turns alerts on for itself. Alerts only (the same ones as on the Notifications page), not trade events.
Signing the device out stops them. The push services (Apple, Google, Mozilla, Microsoft) only see encrypted
messages; the signing key is `vapid.pem` in the data folder.

## Security

- Listens on 127.0.0.1 by default. Tailscale is the recommended way in from other devices; "any device on my network"
  is plain http, so passwords and data cross the wifi unencrypted. For https on a network, put a reverse proxy
  (Caddy, nginx) in front and keep NFIForge on 127.0.0.1; cookies are then marked Secure.
- The container is read-only, drops all Linux capabilities and sees only `/proc`, `/sys/fs/cgroup` and the size of
  the root disk from the host: no Docker socket, no host files.
- The bots' api logins in `.env` are the same ones FreqUI uses: NFIForge only trades on a bot when `write_actions` is
  on and that bot's own `trading` switch is on, but anyone who reads `.env` can trade through freqtrade directly. Keep it owner-only (the installer does), and give freqtrade's api server its own
  password rather than an exchange or system one.
- Adding a bot from the UI sends its password to NFIForge: by default only allowed from the machine itself
  (`bot_editing`).
- Failed sign-ins are limited to 5 per 5 minutes per address.
- Share links are the only pages that open without an account. Their answer is built from percentages, counts and
  times only (a test fails on any amount), the code is 256 random bits of which only a hash is stored, and each
  address gets 60 requests a minute.

## Update

The sidebar shows a note when a newer release is out (`update_check: false` in config.yaml turns that off). What
changed in each version: [CHANGELOG.md](CHANGELOG.md). Updating keeps your config, accounts, bots and history.

**Docker install:** from the folder you installed from:

```bash
cd NFIForge
./install.sh --update
```

It stops NFIForge, backs up your config and data to `~/nfiforge/backups/<date>-v<old>`, pulls the new version,
rebuilds, restarts with the same config and shows what changed. If anything fails, the previous version is started
again.

**pipx install:** download the new `.whl` the same way as when installing, install it over the old one, restart the
service:

```bash
pipx install --force ./nfiforge-<version>-py3-none-any.whl
systemctl --user restart nfiforge
```

Use the file name that was just downloaded (`ls nfiforge-*.whl`); with older wheels in the same folder,
`./nfiforge-*.whl` would match more than one. Check the version afterwards: the sidebar shows it, or
`pipx list | grep nfiforge`.

## Trade actions

Admins can open a trade, add to one, exit all or part of it, cancel its open order, reload it from the exchange or
delete it, from the trade inspector, Positions (**+ new entry**) or Chart. Off by default, two switches:

- `write_actions: true` in `config.yaml` (only in the file, so a signed-in browser can't turn it on)
- the bot's own switch: **Manage Bots → edit → Allow trade actions and bot control**, or `trading: true` under the bot
  in `config.yaml`

The entry, add and exit forms show the live price (price, bid and ask from the exchange every 3 s while the form is
open). **use** puts the ask (buying) or bid (selling) in the limit price; a limit shows its distance from now and a
warning when it would fill straight away.

Each action shows what will be sent first. On a live bot (`dry_run: false`, asked from the bot each time) the coin has
to be typed to confirm. Actions are sent once, never retried, and logged under **Notifications → actions**.

On NFI bots an add can be given a grind level: NFI then counts it in that level and sells it at that level's target.
Adds need a stake. Exits can't pick a grind level (freqtrade tags every manual exit `force_exit`), so a partial exit
isn't counted against an open grind level.

## Bot control

With the same two switches, admins can **pause entries** (open trades are still managed), **start**, **stop** (open
trades are not managed while stopped) or **reload config** (re-reads the config and strategy files), from Bot Health or
the **control** button on the Trading page's Bot card. On a live bot the bot's name is typed to confirm; every click is
logged with the trade actions.

## Locks and blacklist

With the same two switches, admins can lock a pair (or `*` for every pair) for a set time, on one side or both, and
remove locks, from **Pairs → Locks**; and add or remove blacklist entries (a coin, a pair or a pattern) from **Pairs →
Blacklist**. Open trades are still managed. Locks are kept by the bot; blacklist edits last until the bot restarts or
reloads its config. On a live bot the coin (the bot's name for `*`, the pattern itself for a pattern) is typed to
confirm.

## Signal radar

**Signal Radar** shows, for every whitelisted pair, the strategy's entry signals and guard columns per candle over the
last 24 h, and what happened to each signal: traded, blocked (already in a trade on that pair, all slots full, pair
locked, the reason NFI logged when it cancelled the entry, not enough free balance, or the entry order never filled)
or not taken (no reason found). It answers "why didn't the bot take that move". The reasons come from the bot's log
lines NFIForge has kept since it started, so signals from before a restart can show as not taken. Off by default per bot: **Manage Bots → edit → Signal radar**, or `radar: true` under the bot in `config.yaml`.
After each new candle it asks the bot for the last 3 candles of every pair (about 2 s for 100 pairs); watch the bot's
loop time on **Server** after turning it on.

## BTCGate (optional)

[BTCGate](docs/BTCGATE.md) labels the market for every coin: turbulence, trend, fast volume and open interest spikes,
announcement locks, token unlocks, the chance of a big move, plus a ledger that scores its signals. In NFIForge it runs
as a worker process of its own on Binance futures data (about 150 coins picked by volume), separate from the bots. Off
by default; when off nothing of it is loaded.

1. Install the package once (pipx installs; kept through NFIForge updates):
   `pipx inject nfiforge TA-Lib 'btcgate @ git+https://github.com/baxr6/BTCGate.git@6eaa03568401d13ced80782ef61eca7975faf900'`
2. In `config.yaml`: `btcgate: {enabled: true}` (and `memory_mb`, default 4096: the worker restarts above it), then
   restart NFIForge
3. **BTCGate** appears in the menu. The first start loads about 2,500 candles per coin (5-10 minutes), later starts
   about 15 s; labels follow each 5 minute candle by 1-2 minutes

Modules, Telegram alerts and keys are set on **BTCGate → Settings** (admins; the worker restarts by itself). They
are kept in `<data_dir>/btcgate/`: `btcgate.json` (BTCGate's settings, same sections as its own config) and
`btcgate_secret.json` (owner-only: Coinalyze key, Telegram token and chat id). Without a Coinalyze key the direction
label stays empty. The Docker image doesn't include BTCGate yet.

## What works now

- **Trading**: a tab per bot with status, money, gauges, slot cards (liquidation distance, grind adds), today's P&L,
  BTC pulse and event stream; panels can be moved, resized and hidden.
- **Positions** and **Trade History**, with a per-trade inspector (chart, orders, grind ladder, MFE / MAE, NFI custom
  data).
- **Risk & exposure** panel: margin used, real leverage, distance to liquidation, and the open book's result if every
  coin moves ±5 to 30 %.
- **Funding** per open trade and over any range of closed trades, and **drawdown** (deepest, longest under water, %
  of the account) on the realised profit curve.
- **Chart**: the bot's own candles with any of its indicator columns, or 15m to 1d from the exchange, trades marked.
- **Signal Radar**: every pair's signals and guards per candle, and why a signal did or didn't trade.
- **Logs**: kept from when NFIForge starts, filtered and grouped. Freqtrade's api holds only its last 1000 lines, so a
  bot run with `-v` (debug) loses lines; the page says so.
- **Notifications**: alerts (bot down or stuck, close to liquidation, drawdown, disk / RAM, container killed or
  restarted) and trade events, with optional desktop pop-ups and phone push alerts.
- **Analytics**: profit over time, daily calendar, breakdown by tag / exit / pair / time, 95 % ranges, best / worst
  move (MFE / MAE) scatter.
- **Pairs**: why the bot is or isn't trading a pair: whitelist, blacklist, locks, filter reasons; lock / unlock and
  blacklist edits when trade actions are on.
- **Your currency**: equity and P&L also shown in AUD, USD, EUR, GBP, CAD, CHF or JPY at the live USDT market
  rate (Settings → General). Display only; the bots still trade in USDT.
- **Timeline**: equity, events, open slots, server CPU and loop time on one time axis (6 h to 30 d).
- **Server**: host and per-container memory, cpu and restarts, with history. No Docker socket.
- **Manage Bots**, **Bot Health**, **Settings**.
- **Phones**: card layouts, thumb-sized controls, add to the home screen as an app.
- Read-only towards the bots unless trade actions are switched on (above). API tokens in log lines are masked.
- Accounts with admin and viewer roles.

## Run (development)

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp config.example.yaml config.yaml          # edit bot URLs / usernames
export LIVE_FT_PASSWORD='your api_server password'
.venv/bin/nfiforge --config config.yaml
curl -s http://127.0.0.1:8880/api/bots
```

## Frontend (development)

```bash
cd frontend && npm install
npm run dev                                  # http://127.0.0.1:5173, proxies to the backend on :8880
NFIFORGE_API=http://127.0.0.1:8890 npm run dev   # point at another backend
```

Try it without a real bot: `python scripts/demo_fake_bot.py` (fake freqtrade on :18080), then run the backend with a
config whose bot url is `http://127.0.0.1:18080`, username `freqtrader`, password `s3cret`.

## Test

```bash
.venv/bin/ruff check backend && .venv/bin/pytest -q
```

Tests run against a fake freqtrade server (`backend/tests/fake_freqtrade.py`); no real bot needed.

## Licence

MIT
