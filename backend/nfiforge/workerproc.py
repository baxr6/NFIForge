# runs a background worker (btcgate, order flow) as its own process: restarts it when it stops or grows past its
# memory limit and reports how it is doing. a worker crash or memory spike never reaches the dashboard

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path

import psutil

log = logging.getLogger(__name__)

LOG_MAX = 20 * 1024 * 1024  # worker.log is rotated to worker.log.1 at start above this


class WorkerProcess:
  def __init__(self, name: str, module: str, folder: Path, memory_mb: int):
    self.name, self.module, self.folder, self.memory_mb = name, module, folder, memory_mb
    self.proc: asyncio.subprocess.Process | None = None
    self.task: asyncio.Task | None = None
    self.tasks: list[asyncio.Task] = []  # helpers next to the worker (file sharing, following its output)
    self.state: dict = {"running": False, "restarts": 0, "last_exit": None, "rss_mb": None, "started": None}
    self.reloading = False

  async def start(self) -> None:
    self.folder.mkdir(parents=True, exist_ok=True)
    self.task = asyncio.create_task(self._run(), name=self.name)

  def share(self, filename: str, build: Callable[[], object], every: float = 30) -> None:
    # fn() -> <folder>/<filename> as json, written only when it changes; the worker reads it
    self.tasks.append(asyncio.create_task(self._share(filename, build, every), name=f"{self.name}-{filename}"))

  async def _share(self, filename: str, build: Callable[[], object], every: float) -> None:
    path, last = self.folder / filename, None
    while True:
      try:
        value = build()
        if value != last:
          tmp_path = path.with_name(f".{filename}.tmp")
          tmp_path.write_text(json.dumps(value))
          os.replace(tmp_path, path)
          last = value
      except Exception:
        log.exception(f"{self.name} {filename}")
      await asyncio.sleep(every)

  async def _spawn(self) -> None:
    logfile = self.folder / "worker.log"
    if logfile.exists() and logfile.stat().st_size > LOG_MAX:
      os.replace(logfile, self.folder / "worker.log.1")
    with open(logfile, "ab") as out:
      self.proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        self.module,
        "--data",
        str(self.folder),
        stdout=out,
        stderr=out,
        stdin=asyncio.subprocess.DEVNULL,
      )
    self.state.update(running=True, pid=self.proc.pid, started=time.time())
    log.info(f"{self.name} worker started (pid {self.proc.pid})")

  async def _run(self) -> None:
    wait = 5  # doubled before use: 10 s after the first quick crash
    while True:
      await self._spawn()
      reason = await self._watch()
      if self.reloading:  # new settings: straight back up, not a crash
        self.reloading = False
        self.state.update(running=False, pid=None, rss_mb=None)
        continue
      self.state.update(running=False, pid=None, rss_mb=None, last_exit=reason, last_exit_at=time.time())
      self.state["restarts"] += 1
      # quick crashes back off up to 5 minutes; a worker that ran an hour starts again in 10 s
      wait = 10 if time.time() - self.state["started"] > 3600 else min(wait * 2, 300)
      log.warning(f"{self.name} worker {reason}, restarting in {wait}s")
      await asyncio.sleep(wait)

  async def _watch(self) -> str:
    proc = psutil.Process(self.proc.pid)
    while True:
      with contextlib.suppress(TimeoutError):
        code = await asyncio.wait_for(self.proc.wait(), 10)
        return f"exited with code {code}"
      with contextlib.suppress(psutil.Error):
        rss = proc.memory_info().rss / 1e6
        self.state["rss_mb"] = round(rss)
        if rss > self.memory_mb:
          await self._stop_proc()
          return f"used {rss:.0f} MB, over the {self.memory_mb} MB limit"

  async def _stop_proc(self) -> None:
    if not self.proc or self.proc.returncode is not None:
      return
    with contextlib.suppress(ProcessLookupError):
      self.proc.send_signal(signal.SIGTERM)
    try:
      await asyncio.wait_for(self.proc.wait(), 20)
    except TimeoutError:
      with contextlib.suppress(ProcessLookupError):
        self.proc.kill()
      await self.proc.wait()

  async def restart(self) -> None:
    # after a settings change; the run loop starts it again at once
    if self.proc and self.proc.returncode is None:
      self.reloading = True
      await self._stop_proc()

  async def stop(self) -> None:
    for task in self.tasks:
      task.cancel()
    if self.task:
      self.task.cancel()
      with contextlib.suppress(asyncio.CancelledError):
        await self.task
    await self._stop_proc()


def read_json(path: Path) -> dict | None:
  try:
    return json.loads(path.read_text())
  except (OSError, ValueError):
    return None
