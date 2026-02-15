#!/usr/bin/env bash
set -euo pipefail

# Start ONLY the poker44 Room Directory under PM2.
#
# This is intended for "central" deployment where:
# - directory runs on shared infra
# - validators announce rooms to it
# - frontend reads rooms from it
#
# Usage:
#   cd poker44-subnet
#   # bind to all interfaces for remote access
#   DIRECTORY_BIND_HOST=0.0.0.0 DIRECTORY_PORT=8010 \
#   DIRECTORY_SHARED_SECRET=... \
#   pm2 start ... (via this script)
#   bash scripts/deploy/pm2/up-directory.sh

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../../.." && pwd)"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v pm2 >/dev/null 2>&1 || die "pm2 not found"
command -v curl >/dev/null 2>&1 || die "curl not found"

port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "( sport = :$port )" 2>/dev/null | tail -n +2 | grep -q LISTEN
    return $?
  fi

  python3 - "$port" <<'PY' >/dev/null 2>&1 && return 1 || return 0
import socket, sys
port=int(sys.argv[1])
s=socket.socket()
try:
  s.bind(("127.0.0.1", port))
  print("free")
finally:
  s.close()
PY
}

find_free_port() {
  local start_port="$1"
  local max_tries="${2:-400}"
  local p="$start_port"
  local i=0
  while [ "$i" -le "$max_tries" ]; do
    if ! port_in_use "$p"; then
      echo "$p"
      return 0
    fi
    p="$((p + 1))"
    i="$((i + 1))"
  done
  return 1
}

pick_start_port() {
  local raw="${START_PORT:-random}"
  local range_start="${PORT_RANGE_START:-3000}"
  local range_end="${PORT_RANGE_END:-20000}"

  if [[ "$raw" =~ ^[0-9]+$ ]]; then
    echo "$raw"
    return 0
  fi

  python3 - <<PY
import random
print(random.randint(int("$range_start"), int("$range_end")))
PY
}

wait_http() {
  local url="$1"
  local timeout_s="${2:-60}"
  local deadline
  deadline="$(( $(date +%s) + timeout_s ))"
  while true; do
    if curl -sf "$url" >/dev/null 2>&1; then
      return 0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      die "timeout waiting for $url"
    fi
    sleep 0.25
  done
}

pm2_delete_if_exists() {
  local name="$1"
  pm2 delete "$name" >/dev/null 2>&1 || true
}

pm2_prefix="${PM2_PREFIX:-poker44-p2p}"
name="${pm2_prefix}-directory"

directory_secret="${DIRECTORY_SHARED_SECRET:-dev-secret}"
ttl_seconds="${DIRECTORY_TTL_SECONDS:-60}"
cors_origins="${DIRECTORY_CORS_ORIGINS:-*}"
bind_host="${DIRECTORY_BIND_HOST:-0.0.0.0}"

start_port="$(pick_start_port)"
directory_port="${DIRECTORY_PORT:-}"
if [[ -z "$directory_port" ]]; then
  directory_port="$(find_free_port "$start_port")" || die "Failed to find a free directory port near $start_port"
fi

venv_dir="${VENV_DIR:-$repo_dir/directory_env}"

log "Repo: $repo_dir"
log "PM2:  $name"
log "Bind: $bind_host:$directory_port"
log "Venv: $venv_dir"

log "Preparing python venv (directory): $venv_dir"
if [ ! -d "$venv_dir" ]; then
  python3 -m venv "$venv_dir"
fi

log "Installing directory python deps (lightweight)"
"$venv_dir/bin/python" -m pip install --upgrade pip wheel "setuptools~=70.0" >/dev/null
"$venv_dir/bin/python" -m pip install -r "$repo_dir/requirements-directory.txt" >/dev/null

log "Starting room directory"
pm2_delete_if_exists "$name"
cd "$repo_dir"
DIRECTORY_SHARED_SECRET="$directory_secret" \
DIRECTORY_TTL_SECONDS="$ttl_seconds" \
DIRECTORY_CORS_ORIGINS="$cors_origins" \
pm2 start "$venv_dir/bin/python" \
  --name "$name" \
  --cwd "$repo_dir" \
  -- \
  -m uvicorn poker44.p2p.room_directory.app:app \
  --host "$bind_host" --port "$directory_port"

pm2 save >/dev/null 2>&1 || true

wait_http "http://127.0.0.1:${directory_port}/healthz" 60

log "Up."
log "Directory:"
log "  http://127.0.0.1:${directory_port}"
log "Rooms:"
log "  http://127.0.0.1:${directory_port}/rooms"

