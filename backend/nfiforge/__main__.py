# entry point: nfiforge [--config config.yaml] [init | service ... | user ... | pair ...]

from __future__ import annotations

import argparse
import logging
import socket
import sys

import uvicorn

from nfiforge import cli, setup
from nfiforge.app import create_app
from nfiforge.config import CONFIG_HOME, ConfigError, default_config, load_config


def main() -> None:
  parser = argparse.ArgumentParser(prog="nfiforge", description="Real-time dashboard for freqtrade bots")
  parser.add_argument(
    "-c", "--config", help="path to config.yaml (default: ./config.yaml, else ~/.config/nfiforge/config.yaml)"
  )
  parser.add_argument("--log-level", default="info")
  commands = parser.add_subparsers(dest="cmd")
  user_parser = commands.add_parser("user", help="accounts: add, list, password, remove")
  user_parser.add_argument("action", choices=["add", "list", "password", "remove"])
  user_parser.add_argument("username", nargs="?", default="")
  user_parser.add_argument("--role", default="viewer", help="admin or viewer (add)")
  pair_parser = commands.add_parser("pair", help="one-time phone sign-in code for a user (10 minutes)")
  pair_parser.add_argument("username")
  pair_parser.add_argument("--link", action="store_true", help="print sign-in links instead of the bare code")
  commands.add_parser("init", help="set up: port, who can open it, bots, first admin, start at boot")
  service_parser = commands.add_parser(
    "service", help="start at boot with systemd (pipx installs): install, remove, status"
  )
  service_parser.add_argument("action", choices=["install", "remove", "status"])
  args = parser.parse_args()
  # init always sets up the per-user install unless told otherwise; the rest also find a ./config.yaml
  args.config = args.config or str(CONFIG_HOME / "config.yaml" if args.cmd == "init" else default_config())
  try:
    if args.cmd == "init":
      setup.init(args.config)
      return
    if args.cmd == "service":
      setup.service(args.action, args.config)
      return
  except ConfigError as e:
    sys.exit(str(e))
  logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
  try:
    config = load_config(args.config)
  except ConfigError as e:
    print(f"NFIForge cannot start:\n{e}", file=sys.stderr)
    sys.exit(2)
  if args.cmd:
    cli.run(args, config)
    return
  # one server on every listed address (e.g. 127.0.0.1 and the tailscale address, not the whole lan)
  socks = []
  for host in config.hosts:
    sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # freebind: the tailscale address may not exist yet at boot; it starts answering once tailscale is up
    sock.setsockopt(socket.SOL_IP, getattr(socket, "IP_FREEBIND", 15), 1)
    try:
      sock.bind((host, config.port))
    except OSError as e:
      sys.exit(
        f"NFIForge cannot listen on {host}:{config.port}: {e.strerror} (another program, or NFIForge already running?)"
      )
    socks.append(sock)
  server = uvicorn.Server(uvicorn.Config(create_app(config), log_level=args.log_level))
  server.run(sockets=socks)


if __name__ == "__main__":
  main()
