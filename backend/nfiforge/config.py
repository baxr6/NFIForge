# config file loading, secrets come from env vars where possible

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# a pipx install keeps its files in the usual per-user places; docker passes --config /config/config.yaml
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "nfiforge"
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "nfiforge"


def default_config() -> Path:
  # ./config.yaml when there is one (development), else ~/.config/nfiforge/config.yaml
  return Path("config.yaml") if Path("config.yaml").exists() else CONFIG_HOME / "config.yaml"


class ConfigError(Exception):
  # raised with a readable list of what is wrong in the config file
  pass


class BotConfig(BaseModel):
  name: str
  url: str
  username: str
  password: str | None = None
  password_env: str | None = None
  enabled: bool = True
  trading: bool = False  # force entries / exits from nfiforge; also needs write_actions: true
  radar: bool = False  # signal radar: every pair's latest candle after each new candle (one small request per pair)
  container: str | None = None  # docker container name, shown on the bot card (what `docker restart` takes)

  @field_validator("name")
  @classmethod
  def _check_name(cls, value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 40 or any(char in "/\\%?#" or not char.isprintable() for char in value):
      raise ValueError("name: 1-40 characters, no / \\ % ? #")
    return value

  @field_validator("container")
  @classmethod
  def _check_container(cls, value: str | None) -> str | None:
    value = (value or "").strip()
    if value and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", value):
      raise ValueError("container: a docker container name (letters, digits, _ . -)")
    return value or None

  @field_validator("url")
  @classmethod
  def _strip_url(cls, value: str) -> str:
    value = value.rstrip("/")
    if not value.startswith(("http://", "https://")):
      raise ValueError("must start with http:// or https://")
    return value

  @model_validator(mode="after")
  def _resolve_password(self) -> BotConfig:
    if self.password_env:
      env = os.environ.get(self.password_env)
      if env is None:
        raise ValueError(f"env var {self.password_env} is not set")
      self.password = env
    if not self.password:
      raise ValueError("needs password_env (preferred) or password")
    return self


class PollIntervals(BaseModel):
  status: float = 5
  health: float = 5
  balance: float = 15
  profit: float = 60
  whitelist: float = 60
  custom_data: float = 30


class BtcgateConfig(BaseModel):
  enabled: bool = False  # runs the btcgate worker (market regime labels per coin); restart nfiforge after changing
  memory_mb: int = Field(4096, ge=512)  # the worker is restarted when it uses more than this


class OrderflowConfig(BaseModel):
  # the order flow worker (docs/ORDERFLOW.md): records trade streams + fills history; restart nfiforge after changing
  enabled: bool = False
  memory_mb: int = Field(1024, ge=256)  # the worker is restarted when it uses more than this
  max_pairs: int = Field(10, ge=1, le=50)  # pairs recorded at once (the chart's pair first, then open trades)
  watch_open_trades: bool = True  # also record every bot's open-trade pairs
  history_days: int = Field(3, ge=0, le=60)  # filled back from the exchange's archives / api
  retention_days: int = Field(30, ge=1, le=365)
  book: bool = True  # record the order book too (heatmap, dom, large orders): ~5-10 MB per pair per day
  book_history_days: int = Field(0, ge=0, le=14)  # book archives (bybit, gate; binance bands): heavy downloads
  book_retention_days: int = Field(7, ge=1, le=90)
  big_pct: float = Field(0.5, gt=0, le=10)  # a big trade: in the pair's top big_pct % by value (last ~20k trades)
  big_usd: float = Field(0, ge=0)  # ... or at least this many USD (0 = use big_pct)


class AppConfig(BaseModel):
  # address(es) to listen on: 127.0.0.1 = this machine only; add a tailscale or lan address to reach it from
  # other devices (everyone still signs in)
  host: str | list[str] = "127.0.0.1"
  port: int = 8880
  access_token: str | None = None  # from before accounts; ignored
  write_actions: bool = False  # master switch for trade actions; each bot also needs trading: true
  # where admins may add / edit / remove bots: "local" (this machine), "network" (any device), "off"
  bot_editing: Literal["local", "network", "off"] = "local"
  update_check: bool = True  # once a day, asks github if a newer release is out
  data_dir: str = "./data"
  poll: PollIntervals = Field(default_factory=PollIntervals)
  bots: list[BotConfig] = Field(default_factory=list)  # more can be added from Settings
  btcgate: BtcgateConfig = Field(default_factory=BtcgateConfig)
  orderflow: OrderflowConfig = Field(default_factory=OrderflowConfig)

  @model_validator(mode="after")
  def _check(self) -> AppConfig:
    names = [bot.name for bot in self.bots]
    if len(names) != len(set(names)):
      raise ValueError("bot names must be unique")
    return self

  @property
  def hosts(self) -> list[str]:
    return [self.host] if isinstance(self.host, str) else self.host


def load_config(path: str | Path) -> AppConfig:
  path = Path(path)
  if not path.exists():
    raise ConfigError(f"config file not found: {path} (make one with: nfiforge init)")
  try:
    raw = yaml.safe_load(path.read_text()) or {}
  except yaml.YAMLError as e:
    raise ConfigError(f"{path}: not valid YAML: {e}") from e
  try:
    config = AppConfig.model_validate(raw)
    # a relative data_dir sits next to the config file, wherever nfiforge was started from
    config.data_dir = str((path.parent / config.data_dir).resolve())
    return config
  except Exception as e:  # pydantic errors -> one readable line each
    errors = getattr(e, "errors", None)
    if callable(errors):
      lines = [f"  - {'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in errors()]
      raise ConfigError(f"{path} has problems:\n" + "\n".join(lines)) from e
    raise ConfigError(f"{path}: {e}") from e
