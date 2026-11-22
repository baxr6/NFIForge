# Changelog

Newest first. Versions follow `major.minor.patch`: patch = fixes, minor = new features.
Update an install with `./install.sh --update`.

## 1.1.3 (2026-11-22)

- Docker image includes BTCGate (still off until `btcgate: {enabled: true}` in config.yaml)

## 1.1.2 (2026-11-22)

- BTCGate install command points at the public BTCGate repo (the old pinned commit no longer exists)

## 1.1.1 (2026-11-22)

- Bot card: the container name has its own line again, so `last loop … ago` shows instead of being cut off

## 1.1.0 (2026-11-22)

- Bot card: **slots used** next to the state, e.g. `Running · 5/10` (open trades / `max_open_trades`; `5 open` when there
  is no limit)
- Bot card: the bot's **docker container** name, from a new optional per-bot setting `container` (Manage Bots → edit, or
  `container:` under the bot in `config.yaml`). Only shown, so you know what to `docker restart`; NFIForge never talks to
  docker

## 1.0.1 (2026-11-15)

- Trading page: a bot with more than 20 slots shows **all its slot boxes** (up to 60). They stopped at 20

## 1.0.0 (2026-11-15)

- First public release: live positions, equity, grinding and protections for freqtrade bots, with NostalgiaForInfinity
  support, trade actions behind admin accounts, order flow, BTCGate market regime, phone alerts and share links. See
  README.md
