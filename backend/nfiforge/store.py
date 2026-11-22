# nfiforge's own sqlite file: equity snapshots (freqtrade keeps no equity history), notifications, server history,
# and accounts (users with password hashes, sessions and pairing codes stored only as hashes)

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Store:
  def __init__(self, data_dir: str | Path, keep_days: int = 180) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    self.path = Path(data_dir) / "nfiforge.db"
    self.keep_days = keep_days
    connection = self._connect()
    # password and session hashes: owner only (sqlite gives its -wal / -shm files the same mode)
    self.path.chmod(0o600)
    try:
      connection.execute("PRAGMA journal_mode=WAL")
      self._migrate(connection)
    finally:
      connection.close()

  # schema changes run in order, once each; the db remembers how far it got
  MIGRATIONS = [
    "CREATE TABLE IF NOT EXISTS equity (bot TEXT, ts REAL, wallet REAL, open_pnl REAL, PRIMARY KEY (bot, ts))",
    "CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, bot TEXT, kind TEXT, level TEXT, key TEXT,"
    " title TEXT, detail TEXT, cleared REAL)",
    "CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)",
    "CREATE TABLE host_hist (ts REAL PRIMARY KEY, cpu REAL, ram REAL, swap REAL, disk REAL, load REAL, temp REAL)",
    "CREATE TABLE ctr_hist (ts REAL, id TEXT, label TEXT, mem REAL, cpu REAL, PRIMARY KEY (ts, id))",
    "CREATE TABLE loop_hist (ts REAL, bot TEXT, loop_s REAL, PRIMARY KEY (ts, bot))",
    "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE COLLATE NOCASE, pw TEXT, role TEXT,"
    " created REAL, disabled INTEGER DEFAULT 0)",
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id INTEGER, created REAL, expires REAL, last_seen REAL,"
    " agent TEXT)",
    "CREATE TABLE pairs (id TEXT PRIMARY KEY, user_id INTEGER, expires REAL)",
    "CREATE TABLE excursions (bot TEXT, trade_id INTEGER, mfe REAL, mae REAL, tf TEXT, error TEXT, ts REAL,"
    " PRIMARY KEY (bot, trade_id))",
    "CREATE TABLE push (endpoint TEXT PRIMARY KEY, user_id INTEGER, p256dh TEXT, auth TEXT, created REAL, agent TEXT)",
    "CREATE TABLE radar (bot TEXT, pair TEXT, ts REAL, long INTEGER, short INTEGER, tag TEXT, off INTEGER,"
    " PRIMARY KEY (bot, pair, ts))",
    "CREATE TABLE radar_logs (bot TEXT, ts REAL, msg TEXT, PRIMARY KEY (bot, ts, msg))",
    # a fresh bot database numbers trades from 1 again: key on the open time too, so a new #1 never reads the old
    # #1's figures. the old rows are measured again from candles
    "DROP TABLE excursions",
    "CREATE TABLE excursions (bot TEXT, trade_id INTEGER, open_ms INTEGER, mfe REAL, mae REAL, tf TEXT, error TEXT,"
    " ts REAL, PRIMARY KEY (bot, trade_id, open_ms))",
    # what a viewer may see (access.py); empty = everything
    "ALTER TABLE users ADD COLUMN access TEXT",
    # share links (share.py): only a hash of the code is kept
    "CREATE TABLE shares (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name TEXT, bots TEXT, opts TEXT,"
    " created REAL, expires REAL, last_seen REAL, opens INTEGER DEFAULT 0)",
  ]
  SERVER_DAYS = 30
  NOTE_COLS = ("id", "ts", "bot", "kind", "level", "key", "title", "detail", "cleared")

  def _migrate(self, connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(self.MIGRATIONS[version:], start=version + 1):
      connection.execute(sql)
      connection.execute(f"PRAGMA user_version = {i}")
    connection.commit()

  def schema_version(self) -> int:
    connection = self._connect()
    try:
      return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
      connection.close()

  # one short-lived connection per call; closed explicitly so handles never leak
  def _connect(self) -> sqlite3.Connection:
    return sqlite3.connect(self.path, timeout=5)

  def add_equity(self, bot: str, wallet: float, open_pnl: float, timestamp: float | None = None) -> None:
    connection = self._connect()
    try:
      connection.execute(
        "INSERT OR REPLACE INTO equity VALUES (?, ?, ?, ?)", (bot, timestamp or time.time(), wallet, open_pnl)
      )
      connection.execute("DELETE FROM equity WHERE ts < ?", (time.time() - self.keep_days * 86400,))
      connection.commit()
    finally:
      connection.close()

  def equity(self, bot: str, since: float) -> list[dict[str, float]]:
    connection = self._connect()
    try:
      rows = connection.execute(
        "SELECT ts, wallet, open_pnl FROM equity WHERE bot = ? AND ts >= ? ORDER BY ts", (bot, since)
      ).fetchall()
    finally:
      connection.close()
    return [
      {"ts": timestamp, "wallet": wallet, "open_pnl": open_pnl, "equity": wallet + open_pnl}
      for timestamp, wallet, open_pnl in rows
    ]

  # ---------------------------------------------------------------------------
  # NOTIFICATIONS: alerts (raised / cleared) and trade events; read marker in meta
  # ---------------------------------------------------------------------------
  def add_note(self, bot: str, kind: str, level: str, key: str, title: str, detail: str = "") -> dict:
    connection = self._connect()
    try:
      timestamp = time.time()
      cursor = connection.execute(
        "INSERT INTO notes (ts, bot, kind, level, key, title, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (timestamp, bot, kind, level, key, title, detail),
      )
      connection.execute("DELETE FROM notes WHERE ts < ?", (timestamp - self.keep_days * 86400,))
      connection.commit()
      return dict(
        zip(self.NOTE_COLS, (cursor.lastrowid, timestamp, bot, kind, level, key, title, detail, None), strict=True)
      )
    finally:
      connection.close()

  def clear_note(self, note_id: int) -> None:
    connection = self._connect()
    try:
      connection.execute("UPDATE notes SET cleared = ? WHERE id = ?", (time.time(), note_id))
      connection.commit()
    finally:
      connection.close()

  @staticmethod
  def _seen(bots: list[str] | None, host: bool) -> tuple[str, list]:
    # the notes a viewer sees: their bots' (None = every bot), and the server's own when host
    if bots is None and host:
      return "", []
    marks = ", ".join("?" * len(bots or []))
    mine = "1=1" if bots is None else f"bot IN ({marks})" if bots else "0=1"
    sql = f" AND ((bot IS NOT NULL AND bot != '' AND {mine}) OR ((bot IS NULL OR bot = '') AND {int(host)}=1))"
    return sql, list(bots or [])

  def notes(
    self,
    limit: int = 200,
    before: int | None = None,
    kind: str | None = None,
    active: bool = False,
    bots: list[str] | None = None,
    host: bool = True,
  ) -> list:
    seen, args = self._seen(bots, host)
    sql = "SELECT * FROM notes WHERE 1=1" + seen
    if before:
      sql, args = sql + " AND id < ?", [*args, before]
    if kind:
      sql, args = sql + " AND kind = ?", [*args, kind]
    if active:
      sql += " AND kind = 'alert' AND level != 'ok' AND cleared IS NULL"
    connection = self._connect()
    try:
      rows = connection.execute(sql + " ORDER BY id DESC LIMIT ?", [*args, limit]).fetchall()
    finally:
      connection.close()
    return [dict(zip(self.NOTE_COLS, row, strict=True)) for row in rows]

  def read_marker(self) -> int:
    connection = self._connect()
    try:
      row = connection.execute("SELECT v FROM meta WHERE k = 'notes_read'").fetchone()
      return int(row[0]) if row else 0
    finally:
      connection.close()

  def set_read(self, note_id: int) -> None:
    connection = self._connect()
    try:
      # never past the newest note: a bigger number would hide every note still to come
      newest = connection.execute("SELECT COALESCE(MAX(id), 0) FROM notes").fetchone()[0]
      connection.execute("INSERT OR REPLACE INTO meta VALUES ('notes_read', ?)", (str(min(max(note_id, 0), newest)),))
      connection.commit()
    finally:
      connection.close()

  def unread(self, bots: list[str] | None = None, host: bool = True) -> int:
    seen, args = self._seen(bots, host)
    connection = self._connect()
    try:
      return connection.execute(
        "SELECT COUNT(*) FROM notes WHERE id > ?" + seen, (self.read_marker(), *args)
      ).fetchone()[0]
    finally:
      connection.close()

  # ---------------------------------------------------------------------------
  # SERVER HISTORY: host, containers and bot loop times once a minute, 30 days
  # ---------------------------------------------------------------------------
  def add_server(self, host: dict, loops: dict[str, float]) -> None:
    timestamp = time.time()
    connection = self._connect()
    try:
      connection.execute(
        "INSERT OR REPLACE INTO host_hist VALUES (?, ?, ?, ?, ?, ?, ?)",
        (timestamp, *(host.get(key) for key in ("cpu", "ram", "swap", "disk", "load", "temp"))),
      )
      connection.executemany(
        "INSERT OR REPLACE INTO ctr_hist VALUES (?, ?, ?, ?, ?)",
        [
          (timestamp, container["id"], container["label"], container["mem"], container["cpu"])
          for container in host.get("containers") or []
        ],
      )
      connection.executemany(
        "INSERT OR REPLACE INTO loop_hist VALUES (?, ?, ?)", [(timestamp, bot, loop_s) for bot, loop_s in loops.items()]
      )
      old = timestamp - self.SERVER_DAYS * 86400
      for table in ("host_hist", "ctr_hist", "loop_hist"):
        connection.execute(f"DELETE FROM {table} WHERE ts < ?", (old,))
      connection.commit()
    finally:
      connection.close()

  def server_history(self, since: float) -> dict:
    connection = self._connect()
    try:
      host = connection.execute("SELECT * FROM host_hist WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
      containers = connection.execute(
        "SELECT ts, id, label, mem, cpu FROM ctr_hist WHERE ts >= ? ORDER BY ts", (since,)
      ).fetchall()
      loops = connection.execute("SELECT ts, bot, loop_s FROM loop_hist WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
    finally:
      connection.close()
    keys = ("ts", "cpu", "ram", "swap", "disk", "load", "temp")
    return {
      "host": [dict(zip(keys, row, strict=True)) for row in host],
      "containers": [
        {"ts": timestamp, "id": container_id, "label": label, "mem": mem, "cpu": cpu}
        for timestamp, container_id, label, mem, cpu in containers
      ],
      "loops": [{"ts": timestamp, "bot": bot, "loop_s": loop_s} for timestamp, bot, loop_s in loops],
    }

  # ---------------------------------------------------------------------------
  # ACCOUNTS
  # ---------------------------------------------------------------------------
  USER_COLS = ("id", "username", "pw", "role", "created", "disabled", "access")

  def _query(self, sql: str, args: tuple = (), write: bool = False) -> list:
    connection = self._connect()
    try:
      rows = connection.execute(sql, args).fetchall()
      if write:
        connection.commit()
      return rows
    finally:
      connection.close()

  def _user(self, rows: list) -> dict | None:
    return dict(zip(self.USER_COLS, rows[0], strict=True)) if rows else None

  def users(self) -> list[dict]:
    rows = self._query("SELECT * FROM users ORDER BY username")
    return [dict(zip(self.USER_COLS, row, strict=True)) for row in rows]

  def user_by_name(self, username: str) -> dict | None:
    return self._user(self._query("SELECT * FROM users WHERE username = ?", (username,)))

  def user_by_id(self, user_id: int) -> dict | None:
    return self._user(self._query("SELECT * FROM users WHERE id = ?", (user_id,)))

  def add_user(self, username: str, pw_hash: str, role: str) -> int:
    connection = self._connect()
    try:
      cursor = connection.execute(
        "INSERT INTO users (username, pw, role, created) VALUES (?, ?, ?, ?)", (username, pw_hash, role, time.time())
      )
      connection.commit()
      return int(cursor.lastrowid)
    finally:
      connection.close()

  def update_user(self, user_id: int, **fields: object) -> None:
    cols = [key for key in fields if key in ("pw", "role", "disabled", "access")]
    if cols:
      sets = ", ".join(f"{key} = ?" for key in cols)
      self._query(f"UPDATE users SET {sets} WHERE id = ?", (*(fields[key] for key in cols), user_id), write=True)

  def delete_user(self, user_id: int) -> None:
    self._query("DELETE FROM users WHERE id = ?", (user_id,), write=True)
    self.end_sessions(user_id)

  # ---------------------------------------------------------------------------
  # SHARE LINKS
  # ---------------------------------------------------------------------------
  def add_share(self, code_hash: str, name: str, bots: list[str], options: dict, expires: float | None) -> int:
    connection = self._connect()
    try:
      cursor = connection.execute(
        "INSERT INTO shares (code, name, bots, opts, created, expires) VALUES (?, ?, ?, ?, ?, ?)",
        (code_hash, name, json.dumps(bots), json.dumps(options), time.time(), expires),
      )
      connection.commit()
      return int(cursor.lastrowid)
    finally:
      connection.close()

  def shares(self) -> list[tuple]:
    return self._query("SELECT * FROM shares ORDER BY id DESC")

  def share_by_code(self, code_hash: str) -> tuple | None:
    # a link that is still valid; counts the visit
    rows = self._query(
      "SELECT * FROM shares WHERE code = ? AND (expires IS NULL OR expires > ?)", (code_hash, time.time())
    )
    if rows:
      self._query(
        "UPDATE shares SET last_seen = ?, opens = opens + 1 WHERE id = ?", (time.time(), rows[0][0]), write=True
      )
    return rows[0] if rows else None

  def drop_share(self, share_id: int) -> bool:
    connection = self._connect()
    try:
      count = connection.execute("DELETE FROM shares WHERE id = ?", (share_id,)).rowcount
      connection.commit()
      return count > 0
    finally:
      connection.close()

  def admins(self) -> int:
    return self._query("SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0")[0][0]

  # sessions: only sha256(cookie) is kept, so a copy of the database can't be used to sign in
  def add_session(self, sid_hash: str, user_id: int, days: float, agent: str = "") -> None:
    now = time.time()
    self._query(
      "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
      (sid_hash, user_id, now, now + days * 86400, now, agent[:200]),
      write=True,
    )
    self._query("DELETE FROM sessions WHERE expires < ?", (now,), write=True)

  def session_user(self, sid_hash: str) -> dict | None:
    rows = self._query(
      "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ? AND s.expires > ? AND u.disabled = 0",
      (sid_hash, time.time()),
    )
    return self._user(rows)

  def end_session(self, sid_hash: str) -> None:
    self._query("DELETE FROM sessions WHERE id = ?", (sid_hash,), write=True)

  def end_sessions(self, user_id: int) -> None:
    self._query("DELETE FROM sessions WHERE user_id = ?", (user_id,), write=True)
    self.drop_push_user(user_id)

  # phone alert subscriptions (web push), one per device, kept for the user until they sign that device out
  def add_push(self, user_id: int, endpoint: str, p256dh: str, auth: str, agent: str) -> None:
    row = (endpoint, user_id, p256dh, auth, time.time(), agent)
    self._query("INSERT OR REPLACE INTO push VALUES (?, ?, ?, ?, ?, ?)", row, write=True)

  def push_subs(self, user_id: int | None = None) -> list[dict]:
    sql = (
      "SELECT p.endpoint, p.p256dh, p.auth, u.role, u.access FROM push p JOIN users u ON u.id = p.user_id"
      " WHERE u.disabled = 0"
    )
    rows = self._query(sql + " AND p.user_id = ?", (user_id,)) if user_id is not None else self._query(sql)
    return [
      {"endpoint": endpoint, "p256dh": p256dh, "auth": auth, "role": role, "access": access}
      for endpoint, p256dh, auth, role, access in rows
    ]

  def drop_push(self, endpoint: str, user_id: int | None = None) -> None:
    if user_id is None:
      self._query("DELETE FROM push WHERE endpoint = ?", (endpoint,), write=True)
    else:
      self._query("DELETE FROM push WHERE endpoint = ? AND user_id = ?", (endpoint, user_id), write=True)

  def drop_push_user(self, user_id: int) -> None:
    self._query("DELETE FROM push WHERE user_id = ?", (user_id,), write=True)

  def session_count(self, user_id: int) -> int:
    return self._query("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND expires > ?", (user_id, time.time()))[0][0]

  # pairing codes: one-time, short-lived, made by the cli (install.sh --phone) for a user
  def add_pair(self, code_hash: str, user_id: int, minutes: float) -> None:
    self._query("INSERT INTO pairs VALUES (?, ?, ?)", (code_hash, user_id, time.time() + minutes * 60), write=True)

  def claim_pair(self, code_hash: str) -> int | None:
    # one statement takes the code, so two phones racing with the same link can't both get in
    rows = self._query("DELETE FROM pairs WHERE id = ? RETURNING user_id, expires", (code_hash,), write=True)
    self._query("DELETE FROM pairs WHERE expires < ?", (time.time(),), write=True)
    return rows[0][0] if rows and rows[0][1] > time.time() else None

  # ---------------------------------------------------------------------------
  # EXCURSIONS: best / worst price move of each closed trade (% of avg entry, no leverage); error = can't be measured
  # ---------------------------------------------------------------------------
  def add_excursion(
    self,
    bot: str,
    trade_id: int,
    open_ms: int,
    mfe: float | None,
    mae: float | None,
    timeframe: str | None,
    error: str | None,
  ):
    self._query(
      "INSERT OR REPLACE INTO excursions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
      (bot, trade_id, open_ms, mfe, mae, timeframe, error, time.time()),
      write=True,
    )

  # {(trade_id, open ms): (mfe, mae)}
  def excursions(self, bot: str) -> dict[tuple[int, int], tuple[float | None, float | None]]:
    rows = self._query("SELECT trade_id, open_ms, mfe, mae FROM excursions WHERE bot = ?", (bot,))
    return {(trade_id, open_ms): (mfe, mae) for trade_id, open_ms, mfe, mae in rows}

  # ---------------------------------------------------------------------------
  # BOT DATA: what nfiforge keeps per bot, so a bot started on a fresh database can start clean here too. db_sig =
  # the bot's oldest closed trade (id, open ms), how a fresh database is spotted
  # ---------------------------------------------------------------------------
  BOT_PARTS = {
    "equity": ("equity",),
    "notes": ("notes",),
    "excursions": ("excursions",),
    "radar": ("radar", "radar_logs"),
    "loops": ("loop_hist",),
  }

  def bot_data(self, bot: str) -> dict[str, int]:
    count = lambda table: self._query(f"SELECT COUNT(*) FROM {table} WHERE bot = ?", (bot,))[0][0]  # noqa: E731
    return {part: sum(count(table) for table in tables) for part, tables in self.BOT_PARTS.items()}

  # parts: keys of BOT_PARTS; the db_sig always goes, so the bot's database as it is now becomes the known one
  def reset_bot(self, bot: str, parts: list[str]) -> dict[str, int]:
    connection = self._connect()
    try:
      gone = {}
      for part in parts:
        tables = self.BOT_PARTS.get(part, ())
        gone[part] = sum(connection.execute(f"DELETE FROM {table} WHERE bot = ?", (bot,)).rowcount for table in tables)
      keys = [f"db_sig:{bot}", *([f"radar_swept:{bot}"] if "radar" in parts else [])]
      connection.executemany("DELETE FROM meta WHERE k = ?", [(key,) for key in keys])
      connection.commit()
      return gone
    finally:
      connection.close()

  def db_sig(self, bot: str) -> tuple[int, int] | None:
    rows = self._query("SELECT v FROM meta WHERE k = ?", (f"db_sig:{bot}",))
    return tuple(int(part) for part in rows[0][0].split(":")) if rows else None  # type: ignore[return-value]

  def set_db_sig(self, bot: str, signature: tuple[int, int]) -> None:
    self._query(
      "INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"db_sig:{bot}", f"{signature[0]}:{signature[1]}"), write=True
    )

  # ---------------------------------------------------------------------------
  # RADAR: candles with an entry signal or a guard off, the log lines that explain them, and when each bot was last
  # swept, so the radar keeps its days across restarts
  # ---------------------------------------------------------------------------
  def add_radar(self, bot: str, rows: list[tuple[str, float, bool, bool, str, int]]) -> None:
    if rows:
      connection = self._connect()
      try:
        connection.executemany(
          "INSERT OR REPLACE INTO radar VALUES (?, ?, ?, ?, ?, ?, ?)", [(bot, *row) for row in rows]
        )
        connection.commit()
      finally:
        connection.close()

  def radar_rows(self, bot: str, since: float) -> list[tuple[str, float, bool, bool, str, int]]:
    rows = self._query("SELECT pair, ts, long, short, tag, off FROM radar WHERE bot = ? AND ts >= ?", (bot, since))
    return [(pair, timestamp, bool(long), bool(short), tag, off) for pair, timestamp, long, short, tag, off in rows]

  def add_radar_log(self, bot: str, timestamp: float, msg: str) -> None:
    self._query("INSERT OR IGNORE INTO radar_logs VALUES (?, ?, ?)", (bot, timestamp, msg), write=True)

  def radar_logs(self, bot: str, since: float) -> list[tuple[float, str]]:
    return self._query("SELECT ts, msg FROM radar_logs WHERE bot = ? AND ts >= ? ORDER BY ts", (bot, since))

  def radar_swept(self, bot: str) -> float | None:
    rows = self._query("SELECT v FROM meta WHERE k = ?", (f"radar_swept:{bot}",))
    return float(rows[0][0]) if rows else None

  def set_radar_swept(self, bot: str, timestamp: float, before: float) -> None:
    # also drops what has aged out of the radar's window
    connection = self._connect()
    try:
      connection.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"radar_swept:{bot}", str(timestamp)))
      connection.execute("DELETE FROM radar WHERE bot = ? AND ts < ?", (bot, before))
      connection.execute("DELETE FROM radar_logs WHERE bot = ? AND ts < ?", (bot, before))
      connection.commit()
    finally:
      connection.close()
