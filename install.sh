#!/usr/bin/env bash
# nfiforge installer: asks for your bots, tests each login, writes config + .env, starts the container
# run from a checkout to build the image locally, or anywhere to pull the published image
# ./install.sh --update: back up data, fetch the new version, rebuild/pull, restart with the same config
# ./install.sh --add-bot: add one more bot to an existing install, test its login, restart
# ./install.sh --add-user: add a dashboard account (admin or viewer)
# ./install.sh --phone: a link + qr code that signs a phone in as a user (works once, 10 minutes)
set -euo pipefail

# =============================================================================
# HELPERS
# =============================================================================
B=$'\e[1m'; D=$'\e[2m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; C=$'\e[36m'; N=$'\e[0m'
say() { printf '%s\n' "$*"; }
ok() { printf '%s✓%s %s\n' "$G" "$N" "$*"; }
warn() { printf '%s!%s %s\n' "$Y" "$N" "$*"; }
die() { printf '%s✗ %s%s\n' "$R" "$*" "$N" >&2; exit 1; }
ask() { local q=$1 def=${2-} a; read -r -p "$q${def:+ ${D}[$def]${N}}: " a || true; printf '%s' "${a:-$def}"; }
ask_secret() { local q=$1 a; read -r -s -p "$q: " a || true; printf '\n' >&2; printf '%s' "$a"; }
yes_no() { local a; a=$(ask "$1 (y/n)" "${2:-y}"); [[ $a =~ ^[Yy] ]]; }

# login test runs inside the image, on the network nfiforge will use (needs NET and IMAGE)
test_login() {  # url user -> prints ok / 401 / unreachable; password comes in through the environment
  PW="$3" docker run --rm --network "$NET" -e PW --entrypoint python "$IMAGE" -c '
import base64, os, sys, urllib.request, urllib.error
url, user, pw = sys.argv[1].rstrip("/"), sys.argv[2], os.environ.get("PW", "")
req = urllib.request.Request(url + "/api/v1/token/login", method="POST")
req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode())
try:
  urllib.request.urlopen(req, timeout=8); print("ok")
except urllib.error.HTTPError as e:
  print("401" if e.code == 401 else f"http {e.code}")
except Exception as e:
  print(f"unreachable ({type(e).__name__})")
' "$1" "$2"
}

# one bot's questions; sets BOT_NAME BOT_URL BOT_USER BOT_PW (login tested, retried until it works or you skip)
ask_bot() {  # number default-url
  say ""
  BOT_NAME=$(ask "Bot $1 name" "$([[ $1 == 1 ]] && echo Live || echo "Bot $1")")
  BOT_URL=$(ask "  api url" "$2")
  BOT_USER=$(ask "  api username" freqtrader)
  while :; do
    BOT_PW=$(ask_secret "  api password")
    [[ $BOT_PW == *"'"* ]] && { warn "passwords with a single quote ' are not supported yet"; continue; }
    local res
    res=$(test_login "$BOT_URL" "$BOT_USER" "$BOT_PW")
    case $res in
      ok) ok "  login works"; break ;;
      401) warn "  freqtrade rejected that username/password" ;;
      *) warn "  $BOT_URL is $res" ;;
    esac
    yes_no "  Try again" y || { warn "  keeping it anyway, fix it later in $DIR/config.yaml / .env"; break; }
  done
}

# container hardening: read-only image filesystem, no extra privileges, and of the host only /proc, the cgroup
# files (host + container stats) and one file on the root disk (disk usage) - never the whole disk
HARDEN='    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]'
HOSTENV='      NFIFORGE_HOST_ROOT: /host
      NFIFORGE_HOST_DISK: /host/disk'
HOSTMOUNTS='      - /proc:/host/proc:ro
      - /sys/fs/cgroup:/host/sys/fs/cgroup:ro
      - /etc/hostname:/host/disk:ro'

# older installs mounted the whole disk at /host: rewrite those lines in place (keeps everything else)
harden_compose() {  # compose file
  grep -q '^      - /:/host:ro$' "$1" || return 0
  local tmp="$1.new"
  awk -v harden="$HARDEN" -v env="$HOSTENV" -v mounts="$HOSTMOUNTS" '
    /^    restart: unless-stopped$/ { print; print harden; next }
    /^      NFIFORGE_HOST_DISK: \/host$/ { print env; next }
    /^      - \/:\/host:ro$/ { print mounts; next }
    { print }' "$1" > "$tmp" && mv "$tmp" "$1"
  ok "compose file hardened: the whole-disk mount is gone"
}

bot_yaml() {  # number -> the config.yaml entry for the BOT_* answers
  printf '  - name: "%s"\n    url: %s\n    username: %s\n    password_env: NFIFORGE_PW_%s\n' "$BOT_NAME" "$BOT_URL" "$BOT_USER" "$1"
}

SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# accounts live in nfiforge's database; the running container's own cli makes them (it prompts for the password)
nf() { docker exec "$@"; }
tty_flags() { [[ -t 0 ]] && printf -- '-it' || printf -- '-i'; }
first_admin() { nf "$CONTAINER" nfiforge --config /config/config.yaml user list 2>/dev/null | awk '$2 == "admin" && $3 == "" {print $1; exit}'; }
add_user() {  # role
  local name
  name=$(ask "Username" "$([[ $1 == admin ]] && whoami)")
  say "${D}password: 10 or more characters${N}"
  nf "$(tty_flags)" "$CONTAINER" nfiforge --config /config/config.yaml user add "$name" --role "$1"
}
tailscale_ip() { ip -4 -o addr show tailscale0 2>/dev/null | awk '{sub(/\/.*/, "", $4); print $4; exit}'; }
# https address `tailscale serve` forwards to port $1 (the phone app and push need https), empty if none
serve_url() { tailscale serve status --json 2>/dev/null | awk -v p="$1" '
  /"[^"]+\.ts\.net:[0-9]+": *\{/ { match($0, /"[^"]+"/); site = substr($0, RSTART + 1, RLENGTH - 2) }
  /"Proxy":/ && site && ($0 ~ "\"(http://)?(127\\.0\\.0\\.1|localhost):" p "/?\"") { sub(/:443$/, "", site); print "https://" site; exit }'; }

DIR=${NFIFORGE_DIR:-$HOME/nfiforge}
UPDATE=""
ADD=""
PHONE=""
ADDUSER=""
CONTAINER=${NFIFORGE_CONTAINER:-nfiforge}
usage() {
  say "usage: ./install.sh [--update | --add-bot | --add-user | --phone] [--dir PATH]"
  say "  (no option)  interactive install or reconfigure"
  say "  --update     back up data, update to the newest version, restart with the same config"
  say "  --add-bot    add another bot to an existing install (asks, tests the login, restarts)"
  say "  --add-user   add a dashboard account: admin (changes things) or viewer (only looks)"
  say "  --phone      link + qr code that signs a phone or tablet in (works once, for 10 minutes)"
  say "  --dir PATH   install folder (default ~/nfiforge, or \$NFIFORGE_DIR)"
}
while [[ $# -gt 0 ]]; do
  case $1 in
    -u|--update) UPDATE=1 ;;
    -a|--add-bot) ADD=1 ;;
    -p|--phone) PHONE=1 ;;
    --add-user) ADDUSER=1 ;;
    -d|--dir) DIR=${2:?--dir needs a path}; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "unknown option $1" ;;
  esac
  shift
done

say ""
say "${B}NFIForge $([[ -n $UPDATE ]] && echo update || ([[ -n $ADD ]] && echo "add a bot") || ([[ -n $PHONE ]] && echo "phone sign-in") || ([[ -n $ADDUSER ]] && echo "add a user") || echo installer)${N} ${D}real-time dashboard for freqtrade bots${N}"
say ""

# =============================================================================
# CHECKS
# =============================================================================
command -v docker >/dev/null || die "docker is not installed: https://docs.docker.com/engine/install/"
docker info >/dev/null 2>&1 || die "docker is installed but not usable by $(whoami) (start it, or add yourself to the docker group)"
if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null; then COMPOSE=(docker-compose)
else die "docker compose is missing: https://docs.docker.com/compose/install/"; fi
ok "docker and compose found"

if [[ -n $PHONE || -n $ADDUSER ]]; then
  [[ -f $DIR/config.yaml && -f $DIR/docker-compose.yml ]] || die "no install found in $DIR (use --dir, or run ./install.sh first)"
  CONTAINER=$(awk '/container_name:/ {print $2; exit}' "$DIR/docker-compose.yml")
  docker exec "$CONTAINER" true 2>/dev/null || die "NFIForge isn't running (docker logs $CONTAINER)"
fi
if [[ -n $ADDUSER ]]; then
  ROLE=$(ask "Role: admin (changes settings, layouts, bots) or viewer (only looks)" viewer)
  [[ $ROLE == admin || $ROLE == viewer ]] || die "role: admin or viewer"
  add_user "$ROLE" || die "no user added"
  exit 0
fi
if [[ -n $PHONE ]]; then
  # ===========================================================================
  # PHONE: one-time sign-in link for a user; the link holds a code that works once, never a password
  # ===========================================================================
  PORT=$(grep -E '^port:' "$DIR/config.yaml" | awk '{print $2}')
  TS=$(tailscale_ip)
  HOSTS=$(grep -E '^host:' "$DIR/config.yaml" | cut -d: -f2-)
  LAN=""; grep -qE '0\.0\.0\.0' <<<"$HOSTS" && LAN=1
  TSON=""; [[ -n $TS && ( -n $LAN || $HOSTS == *"$TS"* ) ]] && TSON=1
  SERVE=$(serve_url "$PORT"); [[ -n $SERVE ]] && TSON=1
  [[ -n $LAN || -n $TSON ]] || die "the dashboard only opens on this computer; run ./install.sh again and pick Tailscale or your network"
  WHO=$(ask "Sign the phone in as" "$(first_admin)")
  CODE=$(nf "$CONTAINER" nfiforge --config /config/config.yaml pair "$WHO") || die "no code made (is $WHO a user? ./install.sh --add-user)"
  if [[ -n $SERVE ]]; then URL="$SERVE/?pair=$CODE"
  elif [[ -n $TSON ]]; then URL="http://$TS:$PORT/?pair=$CODE"
  else
    IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") {print $(i + 1); exit}}')
    URL="http://${IP:-this-computer}:$PORT/?pair=$CODE"
  fi
  say ""
  if command -v qrencode >/dev/null; then
    qrencode -t ANSIUTF8 -m 2 "$URL"
  else
    say "${D}(for a qr code to scan: sudo apt install qrencode, then run this again)${N}"
  fi
  say ""
  say "  open on the phone: ${B}$URL${N}"
  [[ -n $TSON ]] && say "  ${D}the phone needs Tailscale on${N}"
  say "  ${D}works once, for 10 minutes; the phone stays signed in as $WHO after${N}"
  say ""
  exit 0
fi

if [[ -n $ADD ]]; then
  # ===========================================================================
  # ADD A BOT: same image and network as the install, appended to config + .env, then restart
  # ===========================================================================
  [[ -f $DIR/config.yaml && -f $DIR/docker-compose.yml && -f $DIR/.env ]] || die "no install found in $DIR (use --dir, or run ./install.sh first)"
  # bots: must be the last thing in config.yaml so the new entry can go at the end
  awk '/^bots:/ {b=1; next} b && /^[A-Za-z_]/ {bad=1} END {exit !(b && !bad)}' "$DIR/config.yaml" \
    || die "bots: is not the last section of $DIR/config.yaml; add the bot by hand (see README)"
  CONTAINER=$(awk '/container_name:/ {print $2; exit}' "$DIR/docker-compose.yml")
  IMAGE=$(awk '/image:/ {print $2; exit}' "$DIR/docker-compose.yml")
  docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull -q "$IMAGE" >/dev/null || die "image $IMAGE not found"
  if grep -q 'network_mode: host' "$DIR/docker-compose.yml"; then NET=host; DEFURL=http://127.0.0.1:8080
  else NET=$(awk '/^networks:/ {n=1} n && /name:/ {print $2; exit}' "$DIR/docker-compose.yml"); DEFURL=http://freqtrade:8080; fi
  VERSION=$(docker run --rm --entrypoint python "$IMAGE" -c "import nfiforge; print(nfiforge.__version__)")
  say "bots now: $(grep -c '^  - name:' "$DIR/config.yaml")"
  # next free password slot, so existing ones are never touched
  last=$(grep -oE '^NFIFORGE_PW_[0-9]+' "$DIR/.env" | sed 's/.*_//' | sort -n | tail -1 || true)
  n=$(( ${last:-0} + 1 ))
  ask_bot "$n" "$DEFURL"
  grep -qF "name: \"$BOT_NAME\"" "$DIR/config.yaml" && die "a bot called $BOT_NAME already exists; nothing changed"
  BK="$DIR/backups/$(date +%Y%m%d-%H%M%S)-add-bot"
  mkdir -p "$BK" && cp -a "$DIR/config.yaml" "$BK/" && cp -a "$DIR/.env" "$BK/.env" && chmod 600 "$BK/.env" || die "backup failed, nothing changed"
  # if nfiforge won't start with the new bot, put the old files back and start that
  restore_add() {
    if [[ -z ${DONE-} ]]; then
      cp -a "$BK/config.yaml" "$DIR/config.yaml" && cp -a "$BK/.env" "$DIR/.env"
      (cd "$DIR" && "${COMPOSE[@]}" up -d --force-recreate >/dev/null 2>&1) && warn "the bot was not added; the previous config is back and running"
    fi
  }
  trap restore_add EXIT
  [[ -z $(tail -c1 "$DIR/config.yaml") ]] || echo >> "$DIR/config.yaml"
  bot_yaml "$n" >> "$DIR/config.yaml"
  [[ -z $(tail -c1 "$DIR/.env") ]] || echo >> "$DIR/.env"
  printf "NFIFORGE_PW_%s='%s'\n" "$n" "$BOT_PW" >> "$DIR/.env"
  ok "added $BOT_NAME (backup of the old files: $BK)"
elif [[ -n $UPDATE ]]; then
  # ===========================================================================
  # UPDATE: stop, back up, fetch new code
  # ===========================================================================
  [[ -f $DIR/config.yaml && -f $DIR/docker-compose.yml ]] || die "no install found in $DIR (use --dir, or run ./install.sh first)"
  KEEP=1
  CONTAINER=$(awk '/container_name:/ {print $2; exit}' "$DIR/docker-compose.yml")
  # running container first, else the image the stopped container was made from
  OLD=$(docker exec "$CONTAINER" python -c "import nfiforge; print(nfiforge.__version__)" 2>/dev/null \
    || docker run --rm --entrypoint python "$(docker inspect --format '{{.Image}}' "$CONTAINER" 2>/dev/null)" -c "import nfiforge; print(nfiforge.__version__)" 2>/dev/null \
    || echo unknown)
  say "installed version: v$OLD"
  # stop first so the sqlite file is copied in a consistent state; any failure from here restarts the old version
  restart_old() {
    if [[ -z ${DONE-} ]] && (cd "$DIR" && "${COMPOSE[@]}" start >/dev/null 2>&1); then warn "update stopped, the previous version (v$OLD) is running again"; fi
  }
  trap restart_old EXIT
  (cd "$DIR" && "${COMPOSE[@]}" stop >/dev/null 2>&1) || true
  BK="$DIR/backups/$(date +%Y%m%d-%H%M%S)-v$OLD"
  mkdir -p "$BK"
  cp -a "$DIR/config.yaml" "$DIR/docker-compose.yml" "$BK/" && cp -a "$DIR/data" "$BK/data" || die "backup failed, nothing changed"
  [[ -f $DIR/.env ]] && cp -a "$DIR/.env" "$BK/.env" && chmod 600 "$BK/.env"
  ok "backup: $BK"
  if [[ -d $SRC/.git ]]; then
    # explicit remote + branch: works without upstream tracking set up
    git -C "$SRC" pull --ff-only -q origin "$(git -C "$SRC" rev-parse --abbrev-ref HEAD)" || die "git pull failed (local changes in $SRC conflict?); nothing changed"
    ok "code updated to $(git -C "$SRC" describe --tags --always 2>/dev/null)"
  fi
  harden_compose "$DIR/docker-compose.yml"
else
  DIR=$(ask "Install folder" "$DIR")
  if [[ -f $DIR/config.yaml ]] && ! yes_no "A config already exists in $DIR. Replace it" n; then
    say "keeping the existing config, just updating and restarting"
    KEEP=1
    CONTAINER=$(awk '/container_name:/ {print $2; exit}' "$DIR/docker-compose.yml" 2>/dev/null || echo "$CONTAINER")
  fi
fi
mkdir -p "$DIR/data"

if [[ -z $ADD ]]; then
# =============================================================================
# IMAGE: build from this checkout, or pull the published one
# =============================================================================
# an update keeps whatever image source the install used
CUR_IMAGE=$( [[ -f $DIR/docker-compose.yml ]] && awk '/image:/ {print $2; exit}' "$DIR/docker-compose.yml" || true)
if [[ -f $SRC/Dockerfile && -d $SRC/backend/nfiforge && ( -z $UPDATE || $CUR_IMAGE == nfiforge:local ) ]]; then
  IMAGE=nfiforge:local
  say "building the image from $SRC (first build takes a few minutes)…"
  docker build -q -t "$IMAGE" "$SRC" >/dev/null || die "image build failed"
else
  IMAGE=${NFIFORGE_IMAGE:-${CUR_IMAGE:-ghcr.io/baxr6/nfiforge:latest}}
  docker pull -q "$IMAGE" >/dev/null || die "could not pull $IMAGE"
fi
VERSION=$(docker run --rm --entrypoint python "$IMAGE" -c "import nfiforge; print(nfiforge.__version__)")
ok "image $IMAGE (v$VERSION)"
fi

if [[ -z ${KEEP-} && -z $ADD ]]; then
  # ===========================================================================
  # NETWORK + ACCESS
  # ===========================================================================
  say ""
  say "${B}How does NFIForge reach your bots?${N}"
  say "  1) the bots' api ports are on this machine, e.g. http://127.0.0.1:8080 ${D}(simplest, uses host networking)${N}"
  say "  2) the bots are in a docker network, reached by container name, e.g. http://freqtrade:8080"
  NETMODE=$(ask "Choose" 1)
  if [[ $NETMODE == 2 ]]; then
    say "${D}docker networks with freqtrade containers:${N}"
    for n in $(docker network ls --format '{{.Name}}'); do
      c=$(docker network inspect "$n" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | tr ' ' '\n' | grep -i freq | tr '\n' ' ' || true)
      [[ -n $c ]] && say "  ${C}$n${N}: $c"
    done
    NET=$(ask "Docker network name")
    docker network inspect "$NET" >/dev/null 2>&1 || die "no docker network called $NET"
    DEFURL=http://freqtrade:8080
  else
    NET=host
    DEFURL=http://127.0.0.1:8080
  fi

  PORT=$(ask "Dashboard port" 8880)
  [[ $PORT =~ ^[0-9]+$ ]] || die "port must be a number"
  if command -v ss >/dev/null && ss -ltn | awk '{print $4}' | grep -qE "[:.]$PORT\$"; then
    warn "port $PORT is already in use on this machine"
    yes_no "Use it anyway" n || die "pick another port and run again"
  fi
  say ""
  TS=$(tailscale_ip)
  say "${B}Who can open the dashboard?${N} ${D}(everyone signs in with a username and password)${N}"
  say "  1) only this computer"
  if [[ -n $TS ]]; then say "  2) this computer + my devices on Tailscale ($TS) ${D}(recommended for phones: encrypted, not on the lan)${N}"
  else say "  ${D}2) this computer + Tailscale (not available: no tailscale0 here)${N}"; fi
  say "  3) any device on my network ${D}(plain http: passwords cross the wifi unencrypted)${N}"
  ACCESS=$(ask "Choose" "$([[ -n $TS ]] && echo 2 || echo 1)")
  [[ $ACCESS == 2 && -z $TS ]] && die "Tailscale isn't running here"

  if [[ $NET == host ]]; then
    case $ACCESS in 2) BIND="[127.0.0.1, $TS]" ;; 3) BIND=0.0.0.0 ;; *) BIND=127.0.0.1 ;; esac
  else
    BIND=0.0.0.0  # inside the container; the published ports decide who can reach it
  fi

  # ===========================================================================
  # BOTS: ask, test the login from inside the image (same network it will use)
  # ===========================================================================
  say ""
  say "${B}Bots${N} ${D}(the api_server login from each bot's config, the same one FreqUI uses)${N}"
  BOTS_YAML=""; ENV_LINES=""; n=0
  while :; do
    n=$((n + 1))
    ask_bot "$n" "$DEFURL"
    BOTS_YAML+=$(bot_yaml "$n")$'\n'
    ENV_LINES+="NFIFORGE_PW_$n='$BOT_PW'"$'\n'
    yes_no "Add another bot" n || break
  done

  # ===========================================================================
  # WRITE FILES
  # ===========================================================================
  umask 077
  cat > "$DIR/.env" <<EOF
# nfiforge secrets: bot api passwords (owner-only file, never commit it)
${ENV_LINES}NFIFORGE_PORT=$PORT
EOF
  chmod 600 "$DIR/.env"
  umask 022
  cat > "$DIR/config.yaml" <<EOF
# NFIForge config (written by install.sh). Passwords live in .env next to this file.
host: $BIND
port: $PORT
data_dir: /data
write_actions: false
bots:
$BOTS_YAML
EOF

  if [[ $NET == host ]]; then
    NETBLOCK="    network_mode: host"
  else
    case $ACCESS in
      2) PUB="      - \"127.0.0.1:$PORT:$PORT\"
      - \"$TS:$PORT:$PORT\"" ;;
      3) PUB="      - \"$PORT:$PORT\"" ;;
      *) PUB="      - \"127.0.0.1:$PORT:$PORT\"" ;;
    esac
    NETBLOCK="    ports:
$PUB
    networks: [bots]
networks:
  bots:
    external: true
    name: $NET"
  fi
  cat > "$DIR/docker-compose.yml" <<EOF
# NFIForge (written by install.sh). Update: docker compose pull && docker compose up -d
services:
  nfiforge:
    image: $IMAGE
    container_name: $CONTAINER
    restart: unless-stopped
$HARDEN
    env_file: .env
    command: ["--config", "/config/config.yaml"]
    environment:
$HOSTENV
    volumes:
      - ./config.yaml:/config/config.yaml:ro
      - ./data:/data
$HOSTMOUNTS
$NETBLOCK
EOF
  # the container runs as uid 1000
  chmod 755 "$DIR/data" && chown -R 1000:1000 "$DIR/data" 2>/dev/null || chmod 777 "$DIR/data"
fi

# =============================================================================
# START
# =============================================================================
say ""
if ! out=$(cd "$DIR" && "${COMPOSE[@]}" up -d --force-recreate 2>&1); then printf '%s\n' "$out" >&2; die "could not start the container"; fi
PORT=$(grep -E '^port:' "$DIR/config.yaml" | awk '{print $2}')
for _ in $(seq 1 40); do
  docker exec "$CONTAINER" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/api/health', timeout=2)" >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$CONTAINER" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/api/health', timeout=2)" >/dev/null 2>&1 \
  || die "NFIForge did not come up, see: docker logs $CONTAINER"

DONE=1
ok "NFIForge v$VERSION is running"
# accounts replaced the access token (0.15): drop the old token line, and make the first admin if there is none
if grep -qE '^access_token:' "$DIR/config.yaml"; then
  sed -i '/^access_token:/d' "$DIR/config.yaml" && ok "old access token removed from config.yaml (sign-in uses accounts now)"
fi
if [[ -z $ADD && -z $(first_admin) ]]; then
  say ""
  if [[ -t 0 ]]; then
    say "${B}Make the first admin${N} ${D}(signs in to the dashboard; more users later in Settings or ./install.sh --add-user)${N}"
    until add_user admin; do yes_no "Try again" y || break; done
  fi
  [[ -n $(first_admin) ]] || warn "no admin yet, nobody can sign in: ./install.sh --add-user (pick admin)"
fi
grep -qE '^host: *0\.0\.0\.0' "$DIR/config.yaml" && warn "the dashboard is open to your whole network over plain http; ./install.sh (reconfigure) offers Tailscale instead"
if [[ -n $UPDATE ]]; then
  say "  updated:  v$OLD → v$VERSION"
  if [[ -f $SRC/CHANGELOG.md ]]; then
    say "${D}"; awk -v v="## $VERSION" '$0 ~ "^"v {on=1; next} /^## / {on=0} on' "$SRC/CHANGELOG.md" | sed '/^$/d;s/^/  /'; say "${N}"
  fi
  say "  rollback: cd $SRC && git checkout v$OLD && ./install.sh --update, then copy $BK/data back to $DIR/data"
fi
say ""
say "  open:     ${B}http://127.0.0.1:$PORT${N}"
TS=$(tailscale_ip)
[[ -n $TS ]] && grep -qE "^host:.*($TS|0\.0\.0\.0)" "$DIR/config.yaml" && say "  tailscale: ${B}http://$TS:$PORT${N}"
say "  phone:    ./install.sh --phone"
say "  logs:     docker logs -f $CONTAINER"
say "  stop:     cd $DIR && ${COMPOSE[*]} down"
say "  settings: $DIR/config.yaml, passwords in $DIR/.env"
say ""
