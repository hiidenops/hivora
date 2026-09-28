#!/bin/sh
# Hivora installer (draft of get.hivora.io): installs Docker if needed, then runs
# the Hivora container. Re-running it updates Hivora (new image, same data).
#
#   curl -fsSL https://get.hivora.io | sudo sh            # interactive
#   curl -fsSL https://get.hivora.io | sudo sh -s -- --yes --port 8443
#
# Options: --yes (no questions), --port N (8443), --version TAG (latest),
#          --bind IP (address the panel listens on; default: the LAN address),
#          --image REF (ghcr.io/hiidenops/hivora).
set -eu

IMAGE="ghcr.io/hiidenops/hivora"
VERSION="latest"
PORT="8443"
BIND=""
YES=""
DATA="${HIVORA_INSTALL_DATA:-/opt/hivora/data}"   # same path inside and outside the container:
SRV="${HIVORA_INSTALL_SRV:-/srv/hivora}"         # generated compose files use host paths

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --port) PORT="$2"; shift ;;
    --version) VERSION="$2"; shift ;;
    --bind) BIND="$2"; shift ;;
    --image) IMAGE="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }
ask() {  # ask "question" -> 0 if yes
  [ -n "$YES" ] && return 0
  printf '%s [y/N] ' "$1"
  read -r answer < /dev/tty || return 1
  case "$answer" in y|Y|yes|o|O|oui) return 0 ;; *) return 1 ;; esac
}

[ "$(uname -s)" = "Linux" ] || die "Hivora runs on Linux only."
case "$(uname -m)" in
  x86_64|amd64|aarch64|arm64) ;;
  *) die "unsupported CPU architecture: $(uname -m) (amd64 or arm64 needed)" ;;
esac
[ "$(id -u)" -eq 0 ] || die "run as root (e.g. with sudo)."
case "$PORT" in ''|*[!0-9]*) die "--port must be a number" ;; esac

# --- Docker ---------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  say "Docker is not installed."
  ask "Install it now with the official script (get.docker.com)?" || die "Docker is required."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker 2>/dev/null || true
fi
server=$(docker version --format '{{.Server.Version}}' 2>/dev/null) || die "the Docker daemon does not answer."
major=${server%%.*}
[ "$major" -ge 24 ] 2>/dev/null || die "Docker Engine 24 or newer is needed (found $server)."

# --- host facts -------------------------------------------------------------------
LAN_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')
TZ_NAME=$(timedatectl show -p Timezone --value 2>/dev/null || true)
[ -n "$TZ_NAME" ] || TZ_NAME=$(cat /etc/timezone 2>/dev/null || true)
[ -n "$TZ_NAME" ] || TZ_NAME=$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || true)
[ -n "$TZ_NAME" ] || TZ_NAME="UTC"
PUID=${SUDO_UID:-1000}
PGID=${SUDO_GID:-1000}
[ -n "$BIND" ] || BIND=${LAN_IP:-0.0.0.0}

say "Hivora $VERSION on https://${LAN_IP:-this-server}:$PORT (listening on $BIND)"
say "Data: $DATA   App volumes: $SRV   Timezone: $TZ_NAME   PUID/PGID: $PUID/$PGID"
ask "Continue?" || die "cancelled."

mkdir -p "$DATA" "$SRV"
chmod 700 "$DATA"

# --- (re)create the container ----------------------------------------------------
docker pull "$IMAGE:$VERSION" || docker image inspect "$IMAGE:$VERSION" >/dev/null 2>&1 \
  || die "cannot download $IMAGE:$VERSION"
if docker container inspect hivora >/dev/null 2>&1; then
  say "Replacing the current Hivora container (apps keep running, data is kept)."
  docker rm -f hivora >/dev/null
fi
docker run -d --name hivora --restart unless-stopped \
  -p "$BIND:$PORT:8443" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$DATA:$DATA" -v "$SRV:$SRV" \
  -e HIVORA_DATA_DIR="$DATA" -e HIVORA_VOLUMES_ROOT="$SRV" \
  -e HIVORA_HOST_LAN_IP="$LAN_IP" -e HIVORA_TIMEZONE="$TZ_NAME" \
  -e HIVORA_PUID="$PUID" -e HIVORA_PGID="$PGID" \
  --label io.hivora.self=true \
  "$IMAGE:$VERSION" >/dev/null

say "Waiting for Hivora to start..."
i=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' hivora 2>/dev/null)" = "healthy" ]; do
  i=$((i + 1)); [ $i -gt 60 ] && die "Hivora did not start; see: docker logs hivora"
  sleep 2
done

cat <<INFO

  Hivora is running: https://${LAN_IP:-<server-ip>}:$PORT

  First login: admin / admin (you must choose a new password right away),
  then turn on two-factor authentication in your account settings.
  The certificate is self-signed: your browser warns once, that is expected.

  Hivora controls Docker (root on this machine): do not expose port $PORT to the
  Internet; reach it from your network or through the WireGuard app.

  Update: re-run this script.   Logs: docker logs hivora
  Uninstall: docker rm -f hivora (your apps and $SRV stay; $DATA holds the panel data)

INFO
