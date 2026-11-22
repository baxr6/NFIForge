# what a viewer may see: some bots or all, the pages with their own data, or the percent-only view. admins see
# everything. checked on the server for every request and every live message; the menu only follows it

from __future__ import annotations

import json
import re
from typing import Any

# pages whose data no other page needs; the rest (trading, positions, chart, history, analytics, pairs, bot health)
# read the same bot data, so they come with access to a bot
SECTIONS = ("radar", "orderflow", "btcgate", "logs", "server", "notifications")
FULL = {"bots": None, "pages": None, "percent": False}

# what a percent-only viewer may call: signing in and out, and the percent view of their bots
PERCENT_OK = ("/api/auth/", "/api/health", "/api/view")

_BOT = re.compile(r"^/api/bots/([^/]+)(/.*)?$")


def parse(raw: str | None) -> dict:
  # the stored column; empty = everything (every account made before access existed)
  try:
    access = json.loads(raw) if raw else {}
  except ValueError:
    access = {}
  return {
    "bots": access.get("bots") if isinstance(access.get("bots"), list) else None,
    "pages": access.get("pages") if isinstance(access.get("pages"), list) else None,
    "percent": bool(access.get("percent")),
  }


def clean(body: Any) -> str | None:
  # an access setting from the accounts editor -> the stored column; ValueError says what's wrong
  if body is None:
    return None
  if not isinstance(body, dict):
    raise ValueError("access: an object with bots, pages and percent")
  bots, pages = body.get("bots"), body.get("pages")
  if bots is not None and not (isinstance(bots, list) and all(isinstance(bot, str) and bot for bot in bots)):
    raise ValueError("access.bots: a list of bot names, or null for every bot")
  if pages is not None and not (isinstance(pages, list) and all(page in SECTIONS for page in pages)):
    raise ValueError(f"access.pages: a list of {', '.join(SECTIONS)}, or null for every page")
  access = {
    "bots": sorted(set(bots)) if bots is not None else None,
    "pages": sorted(set(pages)) if pages is not None else None,
    "percent": bool(body.get("percent")),
  }
  return None if access == FULL else json.dumps(access)


class Access:
  def __init__(self, user: dict) -> None:
    self.admin = user.get("role") == "admin"
    access = FULL if self.admin else parse(user.get("access"))
    self.bots: list[str] | None = access["bots"]
    self.pages: list[str] | None = access["pages"]
    self.percent: bool = access["percent"]

  def bot(self, name: str | None) -> bool:
    return self.bots is None or name in self.bots

  def page(self, section: str) -> bool:
    return not self.percent and (self.pages is None or section in self.pages)

  def note(self, note: dict) -> bool:
    # a bot's notes go with the bot; the server's own (disk, ram, containers) with the Server page
    return self.page("notifications") and (self.bot(note["bot"]) if note.get("bot") else self.page("server"))

  def refuse(self, path: str, query: dict) -> str | None:
    # why this api path is closed to the user, or None
    if self.admin:
      return None
    if self.percent:
      return None if path.startswith(PERCENT_OK) else "this account sees the percent view only"
    if match := _BOT.match(path):
      if not self.bot(match.group(1)):
        return "not one of your bots"
      subpath = (match.group(2) or "").split("/")[1:2]
      section = {"radar": "radar", "logs": "logs"}.get(subpath[0] if subpath else "")
      return f"no access to {section}" if section and not self.page(section) else None
    for prefix, section in (
      ("/api/orderflow/", "orderflow"),
      ("/api/btcgate/", "btcgate"),
      ("/api/server/", "server"),
      ("/api/host", "server"),
      ("/api/notifications", "notifications"),
      ("/api/push/", "notifications"),
    ):
      if path.startswith(prefix):
        if not self.page(section):
          return f"no access to {section}"
        if section == "orderflow" and "bot" in query and not self.bot(query["bot"]):
          return "not one of your bots"
    return None

  def message(self, msg: dict) -> bool:
    # whether a live (websocket) message may go to the user
    if self.admin:
      return True
    kind = msg.get("type")
    if kind == "host":
      return self.page("server")
    if kind == "notification":
      return self.note(msg["data"])
    if kind == "notifications_read":
      return self.page("notifications")
    if "bot" in msg:
      return self.bot(msg["bot"])
    return True

  def view(self) -> dict:
    # what the browser gets to shape its menu
    return {"bots": self.bots, "pages": self.pages, "percent": self.percent}
