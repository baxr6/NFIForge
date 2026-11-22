# Sharing, access and export (design)

Three additions, taken from what nfi-desk offers: a share link that shows results without amounts, per-user access
for viewers, and downloading tables as CSV / Excel. Admins keep full access; nothing changes for existing accounts
until an admin changes it.

---

## 1. Share link (results without amounts)

A read-only page anyone with the link can open, without an account. It shows **percentages only**: no balances, stake,
amounts, prices or profit in USDT, so nothing on it can be used to work out the account size.

**Making a link** (Settings → Sharing, admins only)

- Name (for the admin's list), the bots it shows, an optional expiry date.
- What it shows (switches): open positions, recent closed trades, entry tags and exit reasons, bot names. With bot
  names off the bots show as "Bot 1", "Bot 2".
- The address is `/s/<code>`: 32 random bytes, shown once on creation (only a hash is kept, like sessions). Lost
  it? Make a new one.
- The list shows each link's bots, expiry, when it was last opened and how many times. Revoke stops it at once.

**What the page shows** (per bot, all from one server function that only produces these numbers)

| Part | Shown |
|---|---|
| Summary | profit % today / 7 d / 30 d / all, win rate, trades, profit factor, deepest drawdown %, slots in use / total |
| Equity | growth line starting at 100 (realised, from the closed trades) |
| Daily | calendar of daily profit % |
| Open positions | pair, long / short, leverage, time open, profit %, number of buys (no stake, no prices) |
| Closed trades | last 50: pair, side, open / close time, duration, profit %; tag and exit reason if switched on |

Percent of what: the bot's starting balance, as Analytics already does. It refreshes every 30 s; no websocket.

**Safety**

- Only `/s/...` and `/api/share/<code>` open without signing in; every other path still needs an account.
- The share answer is built field by field (an allow list), never by removing fields from existing answers. A test
  feeds fake bots through it and fails on any amount-like key (stake, amount, balance, price, abs profit, wallet).
- Wrong or revoked codes get the same 404 with a small delay; 60 requests a minute per address. `noindex`,
  `no-store`, no referrer.
- NFIForge listens on 127.0.0.1 unless set otherwise; for people outside your network to open a link, it has to be
  reachable (reverse proxy or tunnel). The Help page says so; NFIForge opens nothing by itself.

---

## 2. Per-user access (viewers)

Admins see and do everything, as now. For each **viewer** an admin can set (Settings → Accounts → edit):

- **Bots**: all, or a chosen list. Others are left out everywhere: bot tabs, positions, history, charts, pairs, logs,
  order flow, notifications and the live websocket.
- **Pages** with their own data, each on / off: Signal Radar, Order Flow, BTCGate, Logs, Server, Notifications.
  Trading, Positions, Chart, Trade History, Analytics, Pairs, Bot Health and Help share the same bot data, so they
  come with bot access (hiding one of them in the menu would not stop the data being read).
- **Percent only**: the viewer sees only the share page's view of their bots (section 1), with no amounts anywhere.
  Every other page and api answer is refused for them.

How it is enforced: on the server, on every request, from the user's row (changes apply at once; an open
websocket picks them up within 30 s, the way blocking a user does now). The menu hides what the user can't open,
but the server is the check. Stored as one `access` column on the users table: empty = everything (all existing
viewers stay as they are).

Not included: per-viewer trade actions (they stay admin only) and roles beyond admin / viewer.

---

## 3. Download (CSV / Excel)

A **Download** button on the tables that hold trade data:

| Table | File holds |
|---|---|
| Trade History | the trades that match the current filters (bot, dates, side, tag, ...), every column |
| Positions | the open positions now |
| Analytics | each breakdown table (by tag / exit / pair / time) |
| Trade inspector | that trade's orders |

- **CSV**: one file. **Excel (.xlsx)**: Trade History gets a second sheet with every order of those trades.
- Numbers stay numbers (not text), times in your time zone with the zone in the header, amounts in USDT plus a
  column in your display currency when one is set.
- Made in the browser from the rows already loaded (the history is already loaded whole for filtering), so the file
  matches what the table shows. The .xlsx is written by a small built-in writer (no new library).
- Anyone who can see the table can download it; percent-only viewers and share pages have no download.

---

## Build order

1. Download (smallest, no security impact).
2. Per-user access (server checks + Accounts editor), with tests per page and per bot.
3. Share links (needs the percent-only view, which percent-only viewers then reuse), with the leak test.

---

## As built

- `backend/nfiforge/access.py`: the rules (`Access.refuse` per api path, `.message` per live message, `.note` per
  notification and phone push). Stored as `users.access` (json, empty = everything); admins ignore it.
- `backend/nfiforge/share.py`: `bot_view` builds each bot's answer key by key; account percentages are left out
  (null) when the bot reports no starting capital rather than shown wrong. `shares` table keeps the code's hash.
- Routes: `GET/POST /api/manage/shares`, `DELETE /api/manage/shares/{id}` (admins), `GET /api/share/{code}` (no
  account; 60 a minute per address; wrong / revoked / expired all give the same 404), `GET /api/view` (percent-only
  viewers). Percent-only viewers get no websocket (closed with 4403).
- Tests: `tests/test_access.py`, `tests/test_share.py` (walks every answer for amount-like keys and for any amount
  the fake bot reported).
- Frontend: `lib/download.ts` (csv + a small xlsx writer, checked with openpyxl and LibreOffice),
  `lib/tradeSheets.ts`, `components/DownloadButton.vue`, `views/ShareView.vue` (share links and percent viewers),
  `components/settings/SharesSection.vue`, the access editor in `UsersSection.vue`. Host dials on Trading hide
  without the Server page.
