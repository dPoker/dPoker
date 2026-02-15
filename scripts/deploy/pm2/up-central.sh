#!/usr/bin/env bash
set -euo pipefail

# Deploy a "central" stack under PM2:
# - room directory (FastAPI/uvicorn)
# - platform frontend (Next.js)
#
# Intended topology:
# - directory + frontend live on shared infra
# - validator operators run their own platform backend + validator elsewhere
# - frontend discovers rooms via directory and then connects to the selected validator backend at runtime
#
# Usage:
#   cd poker44-subnet
#   PM2_PREFIX=poker44-central \
#   START_PORT=8010 \
#   DIRECTORY_SHARED_SECRET=dev-secret \
#   bash scripts/deploy/pm2/up-central.sh

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../../.." && pwd)"

# Default workspace layout:
#   <workspace>/poker44-subnet
#   <workspace>/platform/frontend
platform_frontend_dir="${PLATFORM_FRONTEND_DIR:-$repo_dir/../platform/frontend}"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v node >/dev/null 2>&1 || die "node not found"
command -v npm >/dev/null 2>&1 || die "npm not found"
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
  local timeout_s="${2:-90}"
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
directory_name="${pm2_prefix}-directory"
frontend_name="${pm2_prefix}-frontend"

directory_secret="${DIRECTORY_SHARED_SECRET:-dev-secret}"
ttl_seconds="${DIRECTORY_TTL_SECONDS:-60}"
cors_origins="${DIRECTORY_CORS_ORIGINS:-*}"
directory_bind_host="${DIRECTORY_BIND_HOST:-0.0.0.0}"

start_port="$(pick_start_port)"
directory_port="${DIRECTORY_PORT:-}"
frontend_port="${FRONTEND_PORT:-}"

if [[ -z "$directory_port" ]]; then
  directory_port="$(find_free_port "$start_port")" || die "Failed to find a free directory port near $start_port"
fi

if [[ -z "$frontend_port" ]]; then
  frontend_port="$(find_free_port "$((directory_port + 1))")" || die "Failed to find a free frontend port"
fi

directory_url="http://127.0.0.1:${directory_port}"
frontend_url="http://127.0.0.1:${frontend_port}"

venv_dir="${VENV_DIR:-$repo_dir/directory_env}"

log "Repo: $repo_dir"
log "Frontend dir: $platform_frontend_dir"
log "Chosen ports:"
log "  directory: $directory_port ($directory_url)"
log "  frontend:  $frontend_port ($frontend_url)"

# ---------------------------------------------------------------------------
# Room Directory (lightweight python env)
# ---------------------------------------------------------------------------
log "Preparing python venv (directory): $venv_dir"
if [ ! -d "$venv_dir" ]; then
  python3 -m venv "$venv_dir"
fi
log "Installing directory python deps (lightweight)"
"$venv_dir/bin/python" -m pip install --upgrade pip wheel "setuptools~=70.0" >/dev/null
"$venv_dir/bin/python" -m pip install -r "$repo_dir/requirements-directory.txt" >/dev/null

log "Starting room directory (PM2: $directory_name)"
pm2_delete_if_exists "$directory_name"
cd "$repo_dir"
DIRECTORY_SHARED_SECRET="$directory_secret" \
DIRECTORY_TTL_SECONDS="$ttl_seconds" \
DIRECTORY_CORS_ORIGINS="$cors_origins" \
pm2 start "$venv_dir/bin/python" \
  --name "$directory_name" \
  --cwd "$repo_dir" \
  -- \
  -m uvicorn poker44.p2p.room_directory.app:app \
  --host "$directory_bind_host" --port "$directory_port"

# ---------------------------------------------------------------------------
# Frontend (Next.js)
# ---------------------------------------------------------------------------
[ -d "$platform_frontend_dir" ] || die "Platform frontend dir not found: $platform_frontend_dir"

log "Preparing platform frontend (npm deps)"
cd "$platform_frontend_dir"
if [ ! -d node_modules ]; then
  npm install
fi

log "Starting platform frontend (PM2: $frontend_name)"
pm2_delete_if_exists "$frontend_name"
frontend_dist_dir="${NEXT_DIST_DIR:-.next-dev}"
mkdir -p "$platform_frontend_dir/$frontend_dist_dir/static/development" >/dev/null 2>&1 || true

NEXT_DIST_DIR="$frontend_dist_dir" \
NEXT_PUBLIC_DIRECTORY_URL="$directory_url" \
NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://127.0.0.1:3001/api/v1}" \
NEXT_PUBLIC_WS_URL="${NEXT_PUBLIC_WS_URL:-http://127.0.0.1:3001}" \
pm2 start npm \
  --name "$frontend_name" \
  --cwd "$platform_frontend_dir" \
  -- \
  run dev -- -p "$frontend_port"

pm2 save >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------
log "Waiting for directory + frontend"
wait_http "$directory_url/healthz" 60
wait_http "$frontend_url/poker-gameplay/p2p" 120

log "Up."
log "Open:"
log "  $frontend_url/poker-gameplay/p2p"
log "Directory:"
log "  $directory_url/rooms"

