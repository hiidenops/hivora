#!/bin/sh
# Hivora installer: installs Docker if needed, then Hivora; re-running it updates Hivora
# or changes its options (kept in <data>/install.env), apps and data stay.
#
#   curl -fsSL https://github.com/hiidenops/hivora/releases/latest/download/install.sh | sudo sh
#   ... | sudo sh -s -- --yes --access lan --port 8443
#
# Options:
#   --yes             no questions (public access still needs --i-understand)
#   --dry-run         show what would be done, change nothing
#   --version TAG     Hivora version (default: this script's release, else install.env)
#   --image REF       image without tag (default: ghcr.io/hiidenops/hivora)
#   --access MODE     lan (default) or public; vpn and vpn+lan come with the admin VPN
#   --port N          panel port on the machine (8443)
#   --bind IP         address the panel listens on (overrides --access)
#   --data DIR        panel data (/opt/hivora/data)   --srv DIR   app volumes (/srv/hivora)
#   --i-understand    confirm --access public with --yes
#
# Everything is in functions and `main` runs on the last line: a download cut halfway
# runs nothing. install.env is read line by line, never executed, and every value is
# checked before use.
set -eu

SCRIPT_VERSION=""  # the release tag, set by release.yml when publishing
DEFAULT_IMAGE="ghcr.io/hiidenops/hivora"
CONTAINER="hivora"
OS_RELEASE="${HIVORA_OS_RELEASE:-/etc/os-release}"  # tests point it elsewhere
HEALTH_TIMEOUT="${HIVORA_HEALTH_TIMEOUT:-120}"      # seconds

say() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

ask() {  # ask "question" -> 0 if yes (always yes with --yes)
  [ -n "$YES" ] && return 0
  printf '%s [y/N] ' "$1"
  read -r answer < /dev/tty || return 1
  case "$answer" in y|Y|yes|o|O|oui) return 0 ;; *) return 1 ;; esac
}

run() {  # a command that changes something: only shown (on stderr) with --dry-run
  if [ -n "$DRY" ]; then printf '+ %s\n' "$*" >&2; else "$@"; fi
}

usage() { sed -n '9,19p' "$0" 2>/dev/null || true; exit 2; }

# --- options -------------------------------------------------------------------------
parse_args() {
  YES="" DRY="" UNDERSTAND=""
  OPT_VERSION="" OPT_IMAGE="" OPT_ACCESS="" OPT_PORT="" OPT_BIND="" OPT_DATA="" OPT_SRV=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes|-y) YES=1 ;;
      --dry-run) DRY=1 ;;
      --i-understand) UNDERSTAND=1 ;;
      --version|--image|--access|--port|--bind|--data|--srv)
        [ $# -ge 2 ] || die "$1 needs a value"
        case "$1" in
          --version) OPT_VERSION="$2" ;;
          --image) OPT_IMAGE="$2" ;;
          --access) OPT_ACCESS="$2" ;;
          --port) OPT_PORT="$2" ;;
          --bind) OPT_BIND="$2" ;;
          --data) OPT_DATA="$2" ;;
          --srv) OPT_SRV="$2" ;;
        esac
        shift ;;
      -h|--help) usage ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
  done
}

env_value() {  # env_value KEY: KEY="value" from install.env, read, never executed
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^$1=\"\\([^\"]*\\)\"\$/\\1/p" "$ENV_FILE" | tail -n 1
}

matches() {  # matches VALUE REGEX (extended, whole value)
  printf '%s\n' "$1" | grep -Eqx "$2"
}

resolve() {  # command line, then install.env, then detection and defaults
  DATA="${OPT_DATA:-${HIVORA_INSTALL_DATA:-/opt/hivora/data}}"
  matches "$DATA" '/[A-Za-z0-9._/-]*' || die "--data must be an absolute path"
  ENV_FILE="$DATA/install.env"
  OLD_VERSION="$(env_value HIVORA_VERSION)"
  VERSION="${OPT_VERSION:-${SCRIPT_VERSION:-$OLD_VERSION}}"
  [ -n "$VERSION" ] || die "no version to install: use --version TAG (this script is not from a release)"
  IMAGE="${OPT_IMAGE:-$(env_value HIVORA_IMAGE)}"; IMAGE="${IMAGE:-$DEFAULT_IMAGE}"
  ACCESS="${OPT_ACCESS:-$(env_value HIVORA_ACCESS)}"; ACCESS="${ACCESS:-lan}"
  PORT="${OPT_PORT:-$(env_value HIVORA_PORT)}"; PORT="${PORT:-8443}"
  SRV="${OPT_SRV:-$(env_value HIVORA_SRV)}"; SRV="${SRV:-${HIVORA_INSTALL_SRV:-/srv/hivora}}"
  LAN_IP="$(env_value HIVORA_LAN_IP)"
  [ -n "$LAN_IP" ] || LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null \
    | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')" || true
  TZ_NAME="$(env_value HIVORA_TIMEZONE)"
  [ -n "$TZ_NAME" ] || TZ_NAME="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  [ -n "$TZ_NAME" ] || TZ_NAME="$(cat /etc/timezone 2>/dev/null || true)"
  [ -n "$TZ_NAME" ] || TZ_NAME="UTC"
  PUID="$(env_value HIVORA_PUID)"; PUID="${PUID:-${SUDO_UID:-1000}}"
  PGID="$(env_value HIVORA_PGID)"; PGID="${PGID:-${SUDO_GID:-1000}}"

  matches "$VERSION" '[A-Za-z0-9][A-Za-z0-9._-]{0,127}' || die "invalid version: $VERSION"
  matches "$IMAGE" '[a-z0-9][a-z0-9._/:-]{0,254}' || die "invalid image: $IMAGE"
  if ! { matches "$PORT" '[0-9]{1,5}' && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ]; }; then
    die "invalid port: $PORT"
  fi
  matches "$SRV" '/[A-Za-z0-9._/-]*' || die "--srv must be an absolute path"
  [ -z "$LAN_IP" ] || matches "$LAN_IP" '[0-9]{1,3}(\.[0-9]{1,3}){3}' || die "invalid LAN address: $LAN_IP"
  matches "$TZ_NAME" '[A-Za-z0-9_+/-]{1,64}' || TZ_NAME="UTC"
  if ! { matches "$PUID" '[0-9]{1,10}' && matches "$PGID" '[0-9]{1,10}'; }; then
    die "invalid PUID/PGID"
  fi
  case "$ACCESS" in
    lan) BIND="$LAN_IP"; [ -n "$BIND" ] || [ -n "$OPT_BIND" ] \
           || die "no LAN address found: use --bind IP or --access public" ;;
    public) BIND="0.0.0.0" ;;
    vpn|vpn+lan) die "--access $ACCESS comes with the admin VPN (not available yet): use lan or public" ;;
    *) die "invalid --access: $ACCESS (lan or public)" ;;
  esac
  [ -z "$OPT_BIND" ] || BIND="$OPT_BIND"
  matches "$BIND" '[0-9]{1,3}(\.[0-9]{1,3}){3}' || die "invalid --bind address: $BIND"
}

# --- checks (nothing changed yet) --------------------------------------------------------
check_platform() {
  [ "$(uname -s)" = "Linux" ] || die "Hivora runs on Linux only."
  case "$(uname -m)" in
    x86_64|amd64|aarch64|arm64) ;;
    *) die "unsupported CPU architecture: $(uname -m) (amd64 or arm64 needed)" ;;
  esac
  [ "$(id -u)" -eq 0 ] || die "run as root (e.g. with sudo)."
}

os_value() { sed -n "s/^$1=//p" "$OS_RELEASE" 2>/dev/null | tr -d '"' | head -n 1; }

check_os() {  # Debian 12+, Ubuntu 22.04+, Raspberry Pi OS 64-bit (reports "debian")
  os_id="$(os_value ID)" version="$(os_value VERSION_ID)"
  major="${version%%.*}"
  matches "$major" '[0-9]+' || major=0
  case "$os_id" in
    debian) [ "$major" -ge 12 ] && return 0 ;;
    ubuntu) [ "$major" -ge 22 ] && return 0 ;;
  esac
  warn "${os_id:-this system} ${version} is not officially supported (Debian 12+, Ubuntu 22.04+, Raspberry Pi OS 64-bit)."
  ask "Continue anyway?" || die "cancelled."
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    say "Docker is not installed."
    ask "Install it now with the official script (get.docker.com)?" || die "Docker is required."
    if [ -n "$DRY" ]; then
      run sh -c "curl -fsSL https://get.docker.com | sh"
      return 0
    fi
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker 2>/dev/null || true
  fi
  if docker version 2>/dev/null | grep -qi podman; then
    die "Podman is not supported: Hivora needs Docker Engine."
  fi
  server="$(docker version --format '{{.Server.Version}}' 2>/dev/null)" \
    || die "the Docker daemon does not answer."
  major="${server%%.*}"
  if ! { matches "$major" '[0-9]+' && [ "$major" -ge 24 ]; }; then
    die "Docker Engine 24 or newer is needed (found $server)."
  fi
  if docker info --format '{{.SecurityOptions}}' 2>/dev/null | grep -q rootless; then
    die "rootless Docker is not supported: Hivora needs the system Docker daemon."
  fi
}

check_port() {  # free, or already Hivora's own (an update)
  busy="$(ss -ltnH "sport = :$PORT" 2>/dev/null || true)"
  [ -n "$busy" ] || return 0
  if [ -n "$UPDATE" ] && docker port "$CONTAINER" 8443/tcp 2>/dev/null | grep -q ":$PORT\$"; then
    return 0
  fi
  die "port $PORT is already in use on this machine: choose another with --port N"
}

confirm_public() {
  if [ "$ACCESS" != "public" ] || [ -n "$OPT_BIND" ]; then return 0; fi
  warn "The panel will listen on every address of this machine, Internet included."
  warn "Hivora controls Docker (root on this machine); Docker bypasses UFW: the firewall does not protect it."
  if [ -n "$YES" ]; then
    [ -n "$UNDERSTAND" ] || die "--access public with --yes needs --i-understand"
  else
    ask "Expose the panel publicly?" || die "cancelled."
  fi
}

# --- steps ------------------------------------------------------------------------------
backup_panel() {  # before an update, while the old Hivora still runs
  if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]; then
    say "Backing up the panel (database, key, options)..."
    if [ -n "$DRY" ]; then
      run docker exec "$CONTAINER" python -m hivora backup-self
    else
      BACKUP="$(docker exec "$CONTAINER" python -m hivora backup-self)" \
        || die "the panel backup failed; nothing was changed."
      say "Backup: $BACKUP"
    fi
  else
    say "Hivora is not running: no backup now (a pending migration is backed up at startup)."
  fi
}

mounts() {  # the same paths inside and outside: generated compose files use host paths
  printf '%s\n' -v "$DATA:$DATA" -v "$SRV:$SRV" -e "HIVORA_DATA_DIR=$DATA" -e "HIVORA_VOLUMES_ROOT=$SRV"
}

bootstrap() {  # before the server: admin never usable as admin/admin
  say "Preparing the panel..."
  # shellcheck disable=SC2046  # mounts() prints one word per line, no spaces in them
  if [ -n "$DRY" ]; then
    run docker run --rm $(mounts) "$IMAGE:$VERSION" python -m hivora bootstrap
    ADMIN="dry-run"
    return 0
  fi
  # shellcheck disable=SC2046
  out="$(docker run --rm $(mounts) "$IMAGE:$VERSION" python -m hivora bootstrap)" \
    || die "the panel could not be prepared (see above)$(recovery)"
  ADMIN="$(printf '%s\n' "$out" | sed -n 's/^ADMIN=//p')"
  ADMIN_USER="$(printf '%s\n' "$out" | sed -n 's/^ADMIN_USER=//p')"
  ADMIN_PASSWORD="$(printf '%s\n' "$out" | sed -n 's/^ADMIN_PASSWORD=//p')"
}

start() {
  say "Starting Hivora $VERSION..."
  # shellcheck disable=SC2046
  run docker run -d --name "$CONTAINER" --restart unless-stopped \
    -p "$BIND:$PORT:8443" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    $(mounts) \
    -e "HIVORA_HOST_LAN_IP=$LAN_IP" -e "HIVORA_TIMEZONE=$TZ_NAME" \
    -e "HIVORA_PUID=$PUID" -e "HIVORA_PGID=$PGID" -e "HIVORA_ACCESS=$ACCESS" \
    --label io.hivora.self=true \
    "$IMAGE:$VERSION" >/dev/null
  [ -z "$DRY" ] || return 0
  waited=0
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null)" = "healthy" ]; do
    waited=$((waited + 2))
    [ "$waited" -le "$HEALTH_TIMEOUT" ] || die "Hivora did not start; see: docker logs $CONTAINER$(recovery)"
    sleep 2
  done
}

recovery() {  # how to go back, printed after a failure once the old container is gone
  [ -n "$UPDATE" ] || return 0
  printf '\n  To go back: docker rm -f %s' "$CONTAINER"
  [ -z "${BACKUP:-}" ] || printf '; tar -xzf %s -C %s' "$BACKUP" "$DATA"
  [ -z "$OLD_VERSION" ] || printf '; then re-run this script with --version %s' "$OLD_VERSION"
}

write_env() {
  if [ -n "$DRY" ]; then
    run write "$ENV_FILE"
    return 0
  fi
  tmp="$ENV_FILE.tmp"
  (
    umask 077
    {
      echo "# Written by the Hivora installer: its options, read again when it is re-run."
      for key in VERSION IMAGE ACCESS PORT LAN_IP TIMEZONE PUID PGID DATA SRV; do
        case "$key" in
          TIMEZONE) value="$TZ_NAME" ;;
          *) eval "value=\${$key}" ;;  # one of the fixed names above
        esac
        printf 'HIVORA_%s="%s"\n' "$key" "$value"
      done
    } > "$tmp"
  )
  mv "$tmp" "$ENV_FILE"
}

summary() {
  host="$BIND"
  [ "$host" != "0.0.0.0" ] || host="${LAN_IP:-<server-ip>}"
  cat <<INFO

  Hivora $VERSION is running: https://$host:$PORT
INFO
  case "$ADMIN" in
    created|secured) cat <<INFO

  User:     $ADMIN_USER
  Password: $ADMIN_PASSWORD
  Shown once only: write it down, then clear your screen (clear). You will choose
  your own password at first login; then turn on two-factor authentication.
INFO
      ;;
    kept) printf '\n  Existing accounts kept (lost password: docker exec %s python -m hivora reset-admin-password).\n' "$CONTAINER" ;;
  esac
  cat <<INFO

  The certificate is self-signed: your browser warns once, that is expected.
  Options are kept in $ENV_FILE: re-run this script to update or change them.
  Logs: docker logs $CONTAINER   Uninstall: docker rm -f $CONTAINER (apps and $SRV stay)

INFO
}

main() {
  parse_args "$@"
  check_platform
  resolve
  UPDATE=""
  docker container inspect "$CONTAINER" >/dev/null 2>&1 && UPDATE=1
  check_os
  check_docker
  check_port
  confirm_public
  say "Hivora $VERSION ($IMAGE), access: $ACCESS, https://$BIND:$PORT"
  say "Data: $DATA   App volumes: $SRV   Timezone: $TZ_NAME   PUID/PGID: $PUID/$PGID"
  [ -z "$UPDATE" ] || say "An existing Hivora will be backed up and replaced (apps keep running)."
  ask "Continue?" || die "cancelled."

  run mkdir -p "$DATA" "$SRV"
  run chmod 700 "$DATA"
  run docker pull "$IMAGE:$VERSION" || docker image inspect "$IMAGE:$VERSION" >/dev/null 2>&1 \
    || die "cannot download $IMAGE:$VERSION"
  BACKUP=""
  if [ -n "$UPDATE" ]; then
    backup_panel
    run docker rm -f "$CONTAINER" >/dev/null
  fi
  bootstrap
  start
  write_env
  if [ -n "$DRY" ]; then
    say "Dry run: nothing was changed."
    return 0
  fi
  summary
}

main "$@"
