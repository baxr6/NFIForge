# per-container memory, cpu, oom kills and restarts, read from the kernel's cgroup files and the host's process table
# through the read-only host mount. no docker socket: that would give full control of docker, even mounted :ro

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

SCOPE = re.compile(r"docker-([0-9a-f]{64})\.scope")
IN_DOCKER = re.compile(r"docker[-/]([0-9a-f]{64})")
WRAPPERS = {"sleep", "sh", "bash", "tini", "dumb-init", "docker-init", "init", "su-exec", "gosu"}
TICK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _read(path: Path) -> str | None:
  try:
    return path.read_text()
  except OSError:
    return None


def label(argv: list[str]) -> str:
  # what the container runs, from safe parts only: a raw command line can carry passwords or tokens
  if not argv:
    return "?"
  program = Path(argv[0]).name
  names = [Path(arg).name for arg in argv]
  if "freqtrade" in names:
    i = names.index("freqtrade")
    command = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("-") else ""
    options = {argv[j]: argv[j + 1] for j in range(len(argv) - 1) if argv[j] in ("--strategy", "-s", "--config", "-c")}
    strategy = options.get("--strategy") or options.get("-s") or ""
    config = Path(options.get("--config") or options.get("-c") or "").name
    return " · ".join(part for part in (f"freqtrade {command}".strip(), strategy, config) if part)
  if program.startswith("python") and len(argv) > 1:
    script = next((arg for arg in argv[1:] if not arg.startswith("-")), "")
    return f"python {Path(script).name}" if script else program
  return program


class ContainerMonitor:
  def __init__(self, host_root: str = "/") -> None:
    self.root = Path(host_root)
    self.cg = self.root / "sys/fs/cgroup"
    self.state: dict[str, dict[str, Any]] = {}  # by short id
    self.available: bool | None = None
    self._cpu: dict[str, tuple[float, float]] = {}  # id -> (usage seconds, at)
    self._procs: dict[str, tuple[str, float]] = {}  # id -> (label, start time)
    self._procs_at = 0.0
    # kept even while a container is gone, so a stop + start still counts as a restart
    self._started: dict[str, float] = {}
    self.restarts: dict[str, int] = {}
    boot = _read(self.root / "proc/stat") or ""
    match = re.search(r"^btime (\d+)", boot, re.M)
    self._boot = float(match[1]) if match else time.time()

  def _scopes(self) -> dict[str, Path]:
    # docker with systemd: system.slice/docker-<id>.scope; cgroupfs driver: docker/<id>
    out = {}
    for path in (self.cg / "system.slice").glob("docker-*.scope"):
      match = SCOPE.match(path.name)
      if match:
        out[match[1]] = path
    for path in (self.cg / "docker").glob("*"):
      if len(path.name) == 64 and path.is_dir():
        out[path.name] = path
    return out

  def _scan_procs(self, ids: set[str]) -> None:
    # per container: start time of its oldest process (changes on a restart) and a label from its oldest process
    # that isn't a wrapper like `sleep infinity` or a shell
    oldest: dict[str, float] = {}
    named: dict[str, tuple[str, float, bool]] = {}  # id -> (label, start, is a wrapper)
    for proc_dir in (self.root / "proc").iterdir():
      if not proc_dir.name.isdigit():
        continue
      match = IN_DOCKER.search(_read(proc_dir / "cgroup") or "")
      if not match or match[1] not in ids:
        continue
      stat = _read(proc_dir / "stat") or ""
      try:
        start = self._boot + int(stat.rsplit(")", 1)[1].split()[19]) / TICK
      except (IndexError, ValueError):
        continue
      container_id = match[1]
      oldest[container_id] = min(start, oldest.get(container_id, start))
      argv = [arg for arg in (_read(proc_dir / "cmdline") or "").split("\0") if arg]
      wrap = not argv or Path(argv[0]).name in WRAPPERS
      current = named.get(container_id)
      if current is None or (current[2] and not wrap) or (current[2] == wrap and start < current[1]):
        named[container_id] = (label(argv), start, wrap)
    self._procs = {container_id: (named[container_id][0], oldest[container_id]) for container_id in oldest}
    self._procs_at = time.time()

  def sample(self) -> dict[str, dict[str, Any]]:
    scopes = self._scopes()
    self.available = bool(scopes)
    now = time.time()
    if now - self._procs_at > 60 or set(scopes) - set(self._procs):
      self._scan_procs(set(scopes))
    out = {}
    for container_id, path in scopes.items():
      short = container_id[:12]
      mem = _read(path / "memory.current")
      mem_max = (_read(path / "memory.max") or "max").strip()
      events = dict(line.split() for line in (_read(path / "memory.events") or "").splitlines() if " " in line)
      usage = re.search(r"usage_usec (\d+)", _read(path / "cpu.stat") or "")
      used_s = int(usage[1]) / 1e6 if usage else None
      cpu = None
      if used_s is not None and container_id in self._cpu:
        prev_used, prev_at = self._cpu[container_id]
        cpu = max(0.0, (used_s - prev_used) / max(now - prev_at, 1e-6) * 100)  # % of one core
      if used_s is not None:
        self._cpu[container_id] = (used_s, now)
      name, start = self._procs.get(container_id, ("?", None))
      if start:
        if short in self._started and abs(start - self._started[short]) > 2:
          self.restarts[short] = self.restarts.get(short, 0) + 1  # same container, new main process
        self._started[short] = start
      out[short] = {
        "id": short,
        "label": name,
        "mem": int(mem) if mem and mem.strip().isdigit() else None,
        "mem_max": int(mem_max) if mem_max.isdigit() else None,
        "cpu": cpu,
        "oom_kills": int(events.get("oom_kill", 0)),
        "started": start,
        "restarts": self.restarts.get(short, 0),
      }
    for gone in set(self._cpu) - set(scopes):
      del self._cpu[gone]
    self.state = out
    return out
