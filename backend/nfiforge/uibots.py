# bots added from the web ui: data_dir/bots.json, owner-only (it holds their api passwords, like .env).
# bots from config.yaml are never written here and can't be edited from the ui

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from nfiforge.config import BotConfig


class UiBots:
  def __init__(self, data_dir: str | Path) -> None:
    self.path = Path(data_dir) / "bots.json"

  def load(self) -> list[BotConfig]:
    if not self.path.exists():
      return []
    return [BotConfig.model_validate(bot) for bot in json.loads(self.path.read_text())]

  def save(self, bots: list[BotConfig]) -> None:
    self.path.parent.mkdir(parents=True, exist_ok=True)
    # temp file + rename: a crash mid-write never leaves a half file; 0600 from the start
    fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, prefix=".bots.")
    with os.fdopen(fd, "w") as f:
      json.dump(
        [bot.model_dump(include={"name", "url", "username", "password", "trading", "radar"}) for bot in bots],
        f,
        indent=2,
      )
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, self.path)
