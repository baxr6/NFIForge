# the btcgate worker process (nfiforge.workerproc does the starting, restarting and memory limit), plus the bots'
# coin list it reads and the alerts it writes

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import logging
from collections.abc import Callable
from pathlib import Path

from nfiforge.workerproc import WorkerProcess, read_json

log = logging.getLogger(__name__)

INSTALL = "pipx inject nfiforge TA-Lib 'btcgate @ git+https://github.com/baxr6/BTCGate.git@99251a4f22a1a6ca9eb8deadcac6794671d81df5'"

__all__ = ["Supervisor", "read_json"]


class Supervisor(WorkerProcess):
  def __init__(
    self,
    folder: Path,
    memory_mb: int,
    on_signal: Callable[[dict], None] | None = None,
    bot_coins: Callable[[], dict] | None = None,
  ):
    super().__init__("btcgate", "nfiforge.btcgate.worker", folder, memory_mb)
    self.on_signal, self.bot_coins = on_signal, bot_coins
    self.installed = importlib.util.find_spec("btcgate") is not None

  async def start(self) -> None:
    self.folder.mkdir(parents=True, exist_ok=True)
    if not self.installed:
      log.warning(f"btcgate is on but the btcgate package isn't installed: {INSTALL}")
      return
    await super().start()
    if self.on_signal:
      self.tasks.append(asyncio.create_task(self._follow(), name="btcgate-signals"))
    if self.bot_coins:
      # the bots' whitelists and open trades, for the worker's coin list
      self.share("bot_coins.json", self.bot_coins)

  async def _follow(self, every: float = 5) -> None:
    # the worker's alerts (signals.jsonl), from where the file ends now: a restart doesn't resend old ones
    path = self.folder / "signals.jsonl"
    offset = path.stat().st_size if path.exists() else 0
    while True:
      await asyncio.sleep(every)
      try:
        size = path.stat().st_size if path.exists() else 0
        if size < offset:  # the worker started the file over
          offset = 0
        if size == offset:
          continue
        with open(path, "rb") as f:
          f.seek(offset)
          chunk = f.read(size - offset)
        done = chunk.rfind(b"\n") + 1  # a line still being written waits for the next look
        offset += done
        for line in chunk[:done].splitlines():
          with contextlib.suppress(ValueError, KeyError, TypeError):
            self.on_signal(json.loads(line))
      except Exception:
        log.exception("btcgate signals")

  def status(self) -> dict:
    worker = read_json(self.folder / "status.json")
    out = {"installed": self.installed, "install": None if self.installed else INSTALL, "memory_mb": self.memory_mb}
    return out | self.state | {"worker": worker}
