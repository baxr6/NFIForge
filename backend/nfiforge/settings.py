# user settings: one json file in data_dir, same on every device that opens the dashboard

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class GaugeSetting(BaseModel):
  enabled: bool = True
  style: Literal["analog", "segment"] | None = None  # None = the gauge's own default look
  warn: float | None = None
  danger: float | None = None


# every gauge the ui knows; new ids get these defaults the first time they appear
GAUGE_DEFAULTS: dict[str, GaugeSetting] = {
  "cpu": GaugeSetting(warn=70, danger=90),
  "ram": GaugeSetting(warn=75, danger=90),
  "load": GaugeSetting(warn=1.0, danger=1.5),
  "disk": GaugeSetting(warn=80, danger=92),
  "swap": GaugeSetting(enabled=False, warn=30, danger=60),
  "temp": GaugeSetting(enabled=False, warn=75, danger=88),
  "exchange_ms": GaugeSetting(warn=200, danger=350),
  "loop_s": GaugeSetting(warn=10, danger=20),
  "btc_rsi": GaugeSetting(),
  "stake_used": GaugeSetting(),
  "slots_used": GaugeSetting(),
  "drawdown": GaugeSetting(warn=10, danger=20),
  "liq_distance": GaugeSetting(warn=20, danger=10),
}


class AlertSettings(BaseModel):
  api_down_s: float = 60  # bot api unreachable this long
  stuck_min: float = 10  # no bot loop for this long
  liq_pct: float = 15  # an open trade this close to liquidation (% of price)
  drawdown_pct: float = 10  # freqtrade's current drawdown above this
  disk_pct: float = 90  # host disk fuller than this
  ram_pct: float = 92  # host ram fuller than this
  container_mem_pct: float = 90  # a container this close to its memory limit
  trade_events: bool = True  # also keep fills, cancels, protections, warnings from the bot
  browser: bool = False  # desktop pop-ups while a tab is open (each browser asks once)


class Settings(BaseModel):
  timezone: str = "utc"  # "utc" or "local"
  day_boundary: str = "utc"  # "utc" or "freqtrade"
  # also show usdt money in this currency (a direct usdt market on kraken); None = off
  fiat: Literal["AUD", "USD", "EUR", "GBP", "CAD", "CHF", "JPY"] | None = "AUD"
  gauges: dict[str, GaugeSetting] = Field(
    default_factory=lambda: {key: gauge.model_copy() for key, gauge in GAUGE_DEFAULTS.items()}
  )
  alerts: AlertSettings = Field(default_factory=AlertSettings)
  colorblind: bool = False  # up / down in blue / orange instead of green / red
  # order flow worker options changed on the settings page, over config.yaml's (keys of OrderflowConfig, not enabled)
  orderflow: dict[str, Any] = Field(default_factory=dict)
  # per page panel layout from the ui: {"items": [{"i", "x", "y", "w", "h"}], "hidden": [ids]}; empty = ui default
  layouts: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SettingsStore:
  def __init__(self, data_dir: str | Path) -> None:
    self.path = Path(data_dir) / "settings.json"
    self.settings = self._load()

  def _load(self) -> Settings:
    settings = Settings.model_validate(json.loads(self.path.read_text())) if self.path.exists() else Settings()
    for key, gauge in GAUGE_DEFAULTS.items():
      settings.gauges.setdefault(key, gauge.model_copy())
    return settings

  def save(self, settings: Settings) -> Settings:
    for key, gauge in GAUGE_DEFAULTS.items():
      settings.gauges.setdefault(key, gauge.model_copy())
    self.path.parent.mkdir(parents=True, exist_ok=True)
    # temp file + rename so a crash mid-write never leaves a half file
    fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, prefix=".settings.")
    with os.fdopen(fd, "w") as f:
      f.write(settings.model_dump_json(indent=2))
    os.replace(tmp_path, self.path)
    self.settings = settings
    return settings
