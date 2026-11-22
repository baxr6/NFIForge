# pipx / plain python installs: `nfiforge init` asks the same questions as install.sh and writes
# ~/.config/nfiforge/config.yaml; `nfiforge service` runs it at boot as a systemd user service

from __future__ import annotations

import getpass
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
import psutil
import yaml

from nfiforge import REPO, __version__
from nfiforge.config import DATA_HOME, AppConfig, load_config
from nfiforge.updates import newer

UNIT = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user" / "nfiforge.service"


def ask(question: str, default: str = "") -> str:
  answer = input(f"{question}{f' [{default}]' if default else ''}: ").strip()
  return answer or default


def yes(question: str, default: bool = True) -> bool:
  return ask(f"{question} (y/n)", "y" if default else "n").lower().startswith("y")


def tailscale_ip() -> str | None:
  for address in psutil.net_if_addrs().get("tailscale0", []):
    if address.family == socket.AF_INET:
      return address.address
  return None


def lan_ip() -> str | None:
  # the address the default route leaves from; nothing is sent
  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    sock.connect(("1.1.1.1", 80))
    return sock.getsockname()[0]
  except OSError:
    return None
  finally:
    sock.close()


def reachable(config: AppConfig) -> list[str]:
  # addresses other devices can open the dashboard on (tailscale first), none when it only listens locally
  out: list[str] = []
  tailscale = tailscale_ip()
  for host in config.hosts:
    if host in ("0.0.0.0", "::"):
      out += [address for address in (tailscale, lan_ip()) if address]
    elif host not in ("127.0.0.1", "localhost", "::1"):
      out.append(host)
  return list(dict.fromkeys(out))


def serve_urls(port: int) -> list[str]:
  # https addresses `tailscale serve` forwards to the dashboard; the phone app and push need https
  try:
    result = subprocess.run(["tailscale", "serve", "status", "--json"], capture_output=True, text=True, timeout=5)
    web = (yaml.safe_load(result.stdout) or {}).get("Web") or {} if result.returncode == 0 else {}
  except (OSError, subprocess.SubprocessError, yaml.YAMLError):
    return []
  ours = {f"{host}:{port}" for host in ("127.0.0.1", "localhost")}
  return [
    f"https://{site.removesuffix(':443')}"
    for site, handler in web.items()
    if (handler.get("Handlers") or {}).get("/", {}).get("Proxy", "").removeprefix("http://").rstrip("/") in ours
  ]


def test_login(url: str, username: str, password: str) -> str:
  try:
    response = httpx.post(f"{url.rstrip('/')}/api/v1/token/login", auth=(username, password), timeout=8)
  except httpx.HTTPError as e:
    return f"can't reach {url} ({type(e).__name__})"
  return "" if response.status_code == 200 else f"login refused ({response.status_code})"


def ask_bots() -> list[dict]:
  bots: list[dict] = []
  print("\nBots (the api_server login from each bot's config, the same one FreqUI uses)")
  while True:
    number = len(bots) + 1
    bot = {
      "name": ask(f"Bot {number} name", "Live" if number == 1 else f"Bot {number}"),
      "url": ask("  api url", f"http://127.0.0.1:{8079 + number}"),
      "username": ask("  username", "freqtrader"),
      "password": getpass.getpass("  password: "),
    }
    problem = test_login(bot["url"], bot["username"], bot["password"])
    print(f"  ✗ {problem}" if problem else "  ✓ login works")
    if not problem or yes("  keep it anyway", False):
      bots.append(bot)
    if not yes("Add another bot", False):
      return bots


def ask_access() -> str | list[str]:
  tailscale = tailscale_ip()
  print("\nWho can open the dashboard? (everyone signs in with a username and password)")
  print("  1) only this computer")
  print(
    f"  2) this computer + my devices on Tailscale ({tailscale}), recommended for phones"
    if tailscale
    else "  2) (Tailscale not running here)"
  )
  print("  3) any device on my network (plain http: passwords cross the wifi unencrypted)")
  choice = ask("Choose", "2" if tailscale else "1")
  if choice == "2" and tailscale:
    return ["127.0.0.1", tailscale]
  return "0.0.0.0" if choice == "3" else "127.0.0.1"


def init(config_path: str) -> None:
  from nfiforge import cli
  from nfiforge.store import Store

  path = Path(config_path).expanduser()
  print(f"NFIForge setup ({path})")
  if not path.exists() or yes("A config already exists. Replace it", False):
    port = int(ask("Dashboard port", "8880"))
    raw = {
      "host": ask_access(),
      "port": port,
      "data_dir": str(DATA_HOME),
      "write_actions": False,
      "bots": ask_bots(),
    }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # owner-only: it holds the bots' api passwords
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
      f.write("# NFIForge config (written by nfiforge init). Holds the bots' api passwords: keep it owner-only.\n")
      yaml.safe_dump(raw, f, sort_keys=False)
    os.chmod(path, 0o600)
    print(f"✓ wrote {path}")
  config = load_config(path)
  db = Store(config.data_dir)
  if not db.admins():
    print("\nMake the first admin (signs in to the dashboard; more users later in Settings)")
    cli.add_user(db, ask("Username", getpass.getuser()), "admin")
  if shutil.which("systemctl") and yes("\nStart NFIForge now and at every boot"):
    service("install", str(path))
  else:
    print(f"\nstart it with: nfiforge --config {path}")


def _systemctl(*args: str) -> bool:
  return subprocess.run(["systemctl", "--user", *args], check=False).returncode == 0


def service(action: str, config_path: str) -> None:
  if not shutil.which("systemctl"):
    sys.exit("no systemd here; run nfiforge from your own process manager instead")
  if action == "status":
    _systemctl("status", "nfiforge", "--no-pager")
    return
  if action == "remove":
    _systemctl("disable", "--now", "nfiforge")
    UNIT.unlink(missing_ok=True)
    _systemctl("daemon-reload")
    print("✓ service removed (config and data kept)")
    return
  path = Path(config_path).expanduser().resolve()
  load_config(path)  # refuse to install a service that can't start
  UNIT.parent.mkdir(parents=True, exist_ok=True)
  # the venv's own python: keeps working after pipx upgrades, whatever is on PATH
  UNIT.write_text(
    "[Unit]\nDescription=NFIForge dashboard for freqtrade bots\nAfter=network-online.target\n\n"
    f"[Service]\nExecStart={sys.executable} -m nfiforge --config {path}\nRestart=on-failure\nRestartSec=5\n\n"
    "[Install]\nWantedBy=default.target\n"
  )
  if not (_systemctl("daemon-reload") and _systemctl("enable", "--now", "nfiforge")):
    sys.exit("systemd didn't start it; see: journalctl --user -u nfiforge")
  config = load_config(path)
  print(f"✓ running: http://127.0.0.1:{config.port}   logs: journalctl --user -u nfiforge -f")
  # user services stop at logout and wait for a login after boot unless lingering is on
  user = getpass.getuser()
  linger = subprocess.run(["loginctl", "show-user", user, "-p", "Linger"], capture_output=True, text=True, check=False)
  if "Linger=yes" not in linger.stdout and subprocess.run(["loginctl", "enable-linger", user], check=False).returncode:
    print(f"! to start at boot before anyone logs in: sudo loginctl enable-linger {user}")


def update() -> None:
  # pipx installs: the newest release's wheel over this one (injected packages such as btcgate are kept), then restart
  if Path("/.dockerenv").exists():
    sys.exit("docker install: run ./install.sh --update from the NFIForge folder")
  pipx = shutil.which("pipx")
  if not pipx:
    sys.exit("pipx not found; install the release's .whl by hand (README, Update)")
  try:
    response = httpx.get(
      f"https://api.github.com/repos/{REPO}/releases/latest",
      headers={"Accept": "application/vnd.github+json"},
      timeout=15,
    )
    response.raise_for_status()
    release = response.json()
  except (httpx.HTTPError, ValueError) as e:
    sys.exit(f"can't read the latest release from github: {e}")
  latest = str(release.get("tag_name", "")).lstrip("v")
  if not newer(latest, __version__):
    print(f"✓ up to date ({__version__})")
    return
  wheel = next((a for a in release.get("assets", []) if a.get("name", "").endswith(".whl")), None)
  if not wheel:
    sys.exit(f"release {latest} has no .whl yet; try again in a few minutes")
  print(f"updating {__version__} -> {latest}")
  with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / wheel["name"]
    try:
      with httpx.stream("GET", wheel["browser_download_url"], follow_redirects=True, timeout=60) as download:
        download.raise_for_status()
        with path.open("wb") as f:
          for chunk in download.iter_bytes():
            f.write(chunk)
    except httpx.HTTPError as e:
      sys.exit(f"download failed: {e}")
    if subprocess.run([pipx, "install", "--force", str(path)], check=False).returncode:
      sys.exit("pipx install failed (see above)")
  print(f"✓ installed {latest}")
  if UNIT.exists() and shutil.which("systemctl"):
    if _systemctl("restart", "nfiforge"):
      print("✓ service restarted")
    else:
      print("! restart failed; see: journalctl --user -u nfiforge")
  else:
    print("restart NFIForge to use the new version")
