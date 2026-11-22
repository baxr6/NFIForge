# host stats for the server gauges: cpu, ram, swap, disk, load per core, temperature, network; plus per container

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import psutil

from nfiforge.connectors.containers import ContainerMonitor

# sensor names that usually mean "the cpu" (amd, intel, generic)
CPU_SENSORS = ("k10temp", "coretemp", "zenpower", "cpu_thermal", "acpitz")


def cpu_temp() -> float | None:
  try:
    temps = psutil.sensors_temperatures() or {}
  except (AttributeError, OSError):
    return None
  for name in CPU_SENSORS:
    values = [sensor.current for sensor in temps.get(name, []) if sensor.current]
    if values:
      return max(values)
  return None


class HostMonitor:
  def __init__(
    self, publish: Callable[[dict[str, Any]], None], every: float = 5, disk_path: str = "/", host_root: str = "/"
  ) -> None:
    self.publish = publish
    self.containers = ContainerMonitor(host_root)  # reads host_root/proc and host_root/sys/fs/cgroup
    self._n = 0
    self.every = every
    self.disk_path = disk_path
    self.state: dict[str, Any] = {}
    self._task: asyncio.Task | None = None
    self._net = psutil.net_io_counters()
    self._net_t = time.time()
    psutil.cpu_percent(None)  # first call primes the counter

  async def start(self) -> None:
    self._task = asyncio.create_task(self._loop(), name="host")

  async def stop(self) -> None:
    if self._task:
      self._task.cancel()
      await asyncio.gather(self._task, return_exceptions=True)

  def sample(self) -> dict[str, Any]:
    memory, swap, disk = psutil.virtual_memory(), psutil.swap_memory(), psutil.disk_usage(self.disk_path)
    net, now = psutil.net_io_counters(), time.time()
    elapsed = max(now - self._net_t, 1e-6)
    sample = {
      "ts": now,
      "cpu": psutil.cpu_percent(None),
      "ram": memory.percent,
      "swap": swap.percent,
      "disk": disk.percent,
      "disk_free": disk.free,
      "disk_total": disk.total,
      "ram_used": memory.total - memory.available,
      "ram_total": memory.total,
      "load": psutil.getloadavg()[0] / (psutil.cpu_count() or 1),
      "temp": cpu_temp(),
      "net_rx_kbs": (net.bytes_recv - self._net.bytes_recv) / elapsed / 1024,
      "net_tx_kbs": (net.bytes_sent - self._net.bytes_sent) / elapsed / 1024,
      "uptime_s": now - psutil.boot_time(),
    }
    self._net, self._net_t = net, now
    # containers every other sample (10 s): walks the process table
    self._n += 1
    if self._n % 2 == 1:
      try:
        self.containers.sample()
      except OSError:
        self.containers.available = False
    sample["containers"] = list(self.containers.state.values())
    sample["containers_ok"] = self.containers.available
    return sample

  async def _loop(self) -> None:
    while True:
      self.state = await asyncio.to_thread(self.sample)
      self.publish({"type": "host", "data": self.state})
      await asyncio.sleep(self.every)
