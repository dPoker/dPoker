#!/usr/bin/env bash
set -euo pipefail

# Deploy the validator stack under PM2:
# - platform backend (Node + Postgres/Redis via docker compose)
# - bittensor validator (announces a joinable room to the directory)
#
# This is intended for validator operators. Frontend + Directory are expected
# to be deployed separately ("central" infra).
#
# Usage:
#   cd poker44-subnet
#   NETWORK=test NETUID=401 \
#   VALIDATOR_WALLET=poker44-test VALIDATOR_HOTKEY=default \
#   POKER44_DIRECTORY_URL=http://<central-host>:8010 \
#   DIRECTORY_SHARED_SECRET=dev-secret \
#   INTERNAL_EVAL_SECRET=dev-internal-eval-secret \
#   bash scripts/deploy/pm2/up-validator-stack.sh

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../../.." && pwd)"

# Default workspace layout:
#   <workspace>/poker44-subnet
#   <workspace>/platform/backend
platform_backend_dir="${PLATFORM_BACKEND_DIR:-$repo_dir/../platform/backend}"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v node >/dev/null 2>&1 || die "node not found"
command -v npm >/dev/null 2>&1 || die "npm not found"
command -v docker >/dev/null 2>&1 || die "docker not found"
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
  local raw="${START_PORT:-3001}"
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

# ---------------------------------------------------------------------------
# Config (Bittensor)
# ---------------------------------------------------------------------------
netuid="${NETUID:-401}"
network="${NETWORK:-test}"
validator_wallet="${VALIDATOR_WALLET:-poker44-test}"
validator_hotkey="${VALIDATOR_HOTKEY:-default}"
validator_friendly_name="${POKER44_VALIDATOR_NAME:-poker44-validator}"
poll_interval_s="${POLL_INTERVAL_S:-10}"
epoch_length="${EPOCH_LENGTH:-20}"

# ---------------------------------------------------------------------------
# Config (Platform backend)
# ---------------------------------------------------------------------------
pm2_prefix="${PM2_PREFIX:-poker44-validator}"
backend_name="${pm2_prefix}-backend"
validator_name="${pm2_prefix}-validator-${network}-${validator_hotkey}"

internal_eval_secret="${INTERNAL_EVAL_SECRET:-dev-internal-eval-secret}"
cors_origins="${CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}"

start_port="$(pick_start_port)"
backend_port="${BACKEND_PORT:-}"
if [[ -z "$backend_port" ]]; then
  backend_port="$(find_free_port "$start_port")" || die "Failed to find a free backend port near $start_port"
fi

# Platform is local to the validator process. (Public URL may differ; override via env.)
platform_base_url="http://127.0.0.1:${backend_port}"
platform_public_url="${POKER44_PLATFORM_PUBLIC_URL:-$platform_base_url}"
platform_public_url="${platform_public_url%/}"

# ---------------------------------------------------------------------------
# Config (Directory)
# ---------------------------------------------------------------------------
directory_url="${POKER44_DIRECTORY_URL:-}"
directory_url="${directory_url%/}"
directory_secret="${DIRECTORY_SHARED_SECRET:-}"

# ---------------------------------------------------------------------------
# Python env (validator)
# ---------------------------------------------------------------------------
venv_dir="${VENV_DIR:-$repo_dir/validator_env}"

log "Repo: $repo_dir"
log "Platform backend: $platform_backend_dir"
log "Platform base URL:   $platform_base_url"
log "Platform public URL: $platform_public_url"
log "Directory URL: ${directory_url:-<disabled>}"
log "PM2 prefix: $pm2_prefix"
log "Python venv: $venv_dir"

log "Preparing python venv (validator): $venv_dir"
if [ ! -d "$venv_dir" ]; then
  python3 -m venv "$venv_dir"
fi

log "Installing subnet python deps (best-effort idempotent)"
"$venv_dir/bin/python" -m pip install --upgrade pip wheel "setuptools~=70.0" >/dev/null
"$venv_dir/bin/python" -m pip install -r "$repo_dir/requirements.txt" >/dev/null

# NOTE: Installing the package will pull full requirements (torch/bittensor).
# That's intended for validators; do NOT use this venv for the directory-only service.
"$venv_dir/bin/python" -m pip install -e "$repo_dir" >/dev/null

validator_ss58="$("$venv_dir/bin/python" - <<PY
import bittensor as bt
w=bt.Wallet(name="$validator_wallet", hotkey="$validator_hotkey")
print(w.hotkey.ss58_address)
PY
)"
[ -n "$validator_ss58" ] || die "Failed to compute validator hotkey ss58"

# ---------------------------------------------------------------------------
# Platform backend (docker deps + migrations)
# ---------------------------------------------------------------------------
[ -d "$platform_backend_dir" ] || die "Platform backend dir not found: $platform_backend_dir"

log "Preparing platform backend (.env, npm deps, docker, migrations)"
cd "$platform_backend_dir"
if [ ! -f .env ]; then
  cp .env.example .env
fi
if [ ! -d node_modules ]; then
  npm install
fi
npm run docker:up
npm run migration:run:dev

log "Starting platform backend (PM2: $backend_name)"
pm2_delete_if_exists "$backend_name"
PORT="$backend_port" \
INTERNAL_EVAL_SECRET="$internal_eval_secret" \
CORS_ORIGINS="$cors_origins" \
JWT_EXPIRES_IN="${JWT_EXPIRES_IN:-30d}" \
COOKIE_MAX_AGE="${COOKIE_MAX_AGE:-2592000000}" \
pm2 start npm \
  --name "$backend_name" \
  --cwd "$platform_backend_dir" \
  -- \
  run dev

log "Waiting for platform backend health"
wait_http "$platform_base_url/health/live" 90

# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------
log "Starting bittensor validator (PM2: $validator_name)"
pm2_delete_if_exists "$validator_name"

POKER44_PROVIDER="platform" \
POKER44_PLATFORM_BACKEND_URL="$platform_base_url" \
POKER44_PLATFORM_PUBLIC_URL="$platform_public_url" \
POKER44_INTERNAL_EVAL_SECRET="$internal_eval_secret" \
POKER44_DIRECTORY_URL="$directory_url" \
POKER44_DIRECTORY_SHARED_SECRET="$directory_secret" \
POKER44_ANNOUNCE_INTERVAL_S="${POKER44_ANNOUNCE_INTERVAL_S:-10}" \
POKER44_AUTOSIMULATE="${POKER44_AUTOSIMULATE:-false}" \
POKER44_TASK_BATCH_SIZE="${POKER44_TASK_BATCH_SIZE:-10}" \
POKER44_VALIDATOR_ID="${POKER44_VALIDATOR_ID:-$validator_ss58}" \
POKER44_VALIDATOR_NAME="$validator_friendly_name" \
pm2 start "$venv_dir/bin/python" \
  --name "$validator_name" \
  --cwd "$repo_dir" \
  -- \
  "$repo_dir/neurons/validator.py" \
  --netuid "$netuid" \
  --wallet.name "$validator_wallet" \
  --wallet.hotkey "$validator_hotkey" \
  --subtensor.network "$network" \
  --neuron.axon_off \
  --poll_interval_seconds "$poll_interval_s" \
  --neuron.epoch_length "$epoch_length" \
  --logging.debug

pm2 save >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# Optional smoke
# ---------------------------------------------------------------------------
run_smoke="${RUN_SMOKE:-true}"
if [ "${run_smoke,,}" = "true" ]; then
  log "Running smoke (validator stack)"
  POKER44_PLATFORM_BACKEND_URL="$platform_base_url" \
  POKER44_INTERNAL_EVAL_SECRET="$internal_eval_secret" \
  POKER44_VALIDATOR_ID="${POKER44_VALIDATOR_ID:-$validator_ss58}" \
  POKER44_DIRECTORY_URL="$directory_url" \
  bash "$repo_dir/scripts/testnet/smoke_validator_stack.sh"
fi

log "Up."
log "Platform backend:"
log "  $platform_base_url"
log "Validator:"
log "  pm2 logs \"$validator_name\""

