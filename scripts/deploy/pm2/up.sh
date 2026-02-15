#!/usr/bin/env bash
set -euo pipefail

# Deploy the full Poker44 P2P stack under PM2:
# - room directory (FastAPI/uvicorn)
# - platform backend (Node + Postgres/Redis via docker compose)
# - platform frontend (Next.js)
# - bittensor miner(s) + validator (testnet/mainnet), announcing rooms to directory
#
# Ports:
# - Choose a START_PORT (default: random) and we will pick the first free ports
#   for frontend/backend/directory in order.
#
# Usage (example):
#   cd poker44-subnet
#   START_PORT=3000 \
#   NETWORK=test NETUID=401 \
#   VALIDATOR_WALLET=poker44-test VALIDATOR_HOTKEY=default \
#   MINER_WALLET=owner MINER_HOTKEYS=miner1 \
#   bash scripts/deploy/pm2/up.sh

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../../.." && pwd)"

# Default workspace layout:
#   <workspace>/poker44-subnet
#   <workspace>/platform/backend
#   <workspace>/platform/frontend
platform_backend_dir="${PLATFORM_BACKEND_DIR:-$repo_dir/../platform/backend}"
platform_frontend_dir="${PLATFORM_FRONTEND_DIR:-$repo_dir/../platform/frontend}"

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

  # Fallback: try binding with python (best-effort).
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

  # random
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

log "Repo: $repo_dir"
log "Platform backend: $platform_backend_dir"
log "Platform frontend: $platform_frontend_dir"

# ---------------------------------------------------------------------------
# Config (Bittensor)
# ---------------------------------------------------------------------------
netuid="${NETUID:-401}"
network="${NETWORK:-test}"

validator_wallet="${VALIDATOR_WALLET:-poker44-test}"
validator_hotkey="${VALIDATOR_HOTKEY:-default}"

miner_wallet="${MINER_WALLET:-owner}"
miner_hotkeys_csv="${MINER_HOTKEYS:-miner1}"

poll_interval_s="${POLL_INTERVAL_S:-10}"
epoch_length="${EPOCH_LENGTH:-20}"

# ---------------------------------------------------------------------------
# Config (P2P services)
# ---------------------------------------------------------------------------
pm2_prefix="${PM2_PREFIX:-poker44-p2p}"
venv_dir="${VENV_DIR:-$repo_dir/validator_env}"

directory_secret="${DIRECTORY_SHARED_SECRET:-dev-secret}"
directory_ttl_seconds="${DIRECTORY_TTL_SECONDS:-60}"
internal_eval_secret="${INTERNAL_EVAL_SECRET:-dev-internal-eval-secret}"

task_batch_size="${POKER44_TASK_BATCH_SIZE:-10}"
autosimulate="${POKER44_AUTOSIMULATE:-true}"

start_port="$(pick_start_port)"
frontend_port="$(find_free_port "$start_port")" || die "Failed to find a free frontend port near $start_port"
backend_port="$(find_free_port "$((frontend_port + 1))")" || die "Failed to find a free backend port"
directory_port="$(find_free_port "$((backend_port + 1))")" || die "Failed to find a free directory port"

platform_url="http://127.0.0.1:${backend_port}"
frontend_url="http://127.0.0.1:${frontend_port}"
directory_url="http://127.0.0.1:${directory_port}"

# Miner axon ports (optional, but needed when running miners locally)
miner_axon_port_base="${MINER_AXON_PORT_BASE:-}"
if [ -z "$miner_axon_port_base" ]; then
  miner_axon_port_base="$(find_free_port "$((directory_port + 100))" 2000)" || die "Failed to find a free miner axon port"
fi

cors_origins="${CORS_ORIGINS:-http://localhost:${frontend_port},http://127.0.0.1:${frontend_port}}"

log "Chosen ports:"
log "  frontend:  $frontend_port ($frontend_url)"
log "  backend:   $backend_port ($platform_url)"
log "  directory: $directory_port ($directory_url)"
log "  miner axon base: $miner_axon_port_base"

# Persist config for convenience (never commit this file).
deploy_env_file="$repo_dir/.p2p_deploy.env"
cat >"$deploy_env_file" <<EOF
START_PORT=$start_port
FRONTEND_PORT=$frontend_port
BACKEND_PORT=$backend_port
DIRECTORY_PORT=$directory_port
MINER_AXON_PORT_BASE=$miner_axon_port_base

FRONTEND_URL=$frontend_url
PLATFORM_URL=$platform_url
DIRECTORY_URL=$directory_url

DIRECTORY_SHARED_SECRET=$directory_secret
INTERNAL_EVAL_SECRET=$internal_eval_secret

NETWORK=$network
NETUID=$netuid
VALIDATOR_WALLET=$validator_wallet
VALIDATOR_HOTKEY=$validator_hotkey
MINER_WALLET=$miner_wallet
MINER_HOTKEYS=$miner_hotkeys_csv
EOF

# ---------------------------------------------------------------------------
# Python env (subnet)
# ---------------------------------------------------------------------------
log "Preparing python venv: $venv_dir"
if [ ! -d "$venv_dir" ]; then
  python3 -m venv "$venv_dir"
fi

log "Installing subnet python deps (best-effort idempotent)"
"$venv_dir/bin/python" -m pip install --upgrade pip wheel "setuptools~=70.0" >/dev/null
"$venv_dir/bin/python" -m pip install -r "$repo_dir/requirements.txt" >/dev/null
"$venv_dir/bin/python" -m pip install -e "$repo_dir" >/dev/null

validator_ss58="$("$venv_dir/bin/python" - <<PY
import bittensor as bt
w=bt.Wallet(name="$validator_wallet", hotkey="$validator_hotkey")
print(w.hotkey.ss58_address)
PY
)"
[ -n "$validator_ss58" ] || die "Failed to compute validator hotkey ss58"

# Resolve miner SS58 addresses for query targeting (best-effort).
miner_hotkeys=()
IFS=',' read -ra _raw_hks <<<"$miner_hotkeys_csv"
for hk in "${_raw_hks[@]}"; do
  hk="$(echo "$hk" | tr -d '[:space:]')"
  [ -n "$hk" ] || continue
  miner_hotkeys+=("$hk")
done
[ "${#miner_hotkeys[@]}" -ge 1 ] || die "MINER_HOTKEYS is empty"

miner_ss58_csv="$("$venv_dir/bin/python" - <<PY
import bittensor as bt
out=[]
for hk in "$miner_hotkeys_csv".split(","):
  hk=hk.strip()
  if not hk:
    continue
  w=bt.Wallet(name="$miner_wallet", hotkey=hk)
  out.append(w.hotkey.ss58_address)
print(",".join(out))
PY
)"

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

# ---------------------------------------------------------------------------
# PM2 apps
# ---------------------------------------------------------------------------
directory_name="${pm2_prefix}-directory"
backend_name="${pm2_prefix}-backend"
frontend_name="${pm2_prefix}-frontend"
validator_name="${pm2_prefix}-validator-${network}-${validator_hotkey}"

log "Starting room directory (PM2: $directory_name)"
pm2_delete_if_exists "$directory_name"
cd "$repo_dir"
DIRECTORY_SHARED_SECRET="$directory_secret" \
DIRECTORY_TTL_SECONDS="$directory_ttl_seconds" \
DIRECTORY_CORS_ORIGINS="$cors_origins" \
pm2 start "$venv_dir/bin/python" \
  --name "$directory_name" \
  --cwd "$repo_dir" \
  -- \
  -m uvicorn poker44.p2p.room_directory.app:app \
  --host 127.0.0.1 --port "$directory_port"

log "Starting platform backend (PM2: $backend_name)"
pm2_delete_if_exists "$backend_name"
PORT="$backend_port" \
INTERNAL_EVAL_SECRET="$internal_eval_secret" \
CORS_ORIGINS="$cors_origins" \
# Keep auth sessions persistent in dev. Backend uses HTTP-only cookies (no localStorage token).
JWT_EXPIRES_IN="${JWT_EXPIRES_IN:-30d}" \
COOKIE_MAX_AGE="${COOKIE_MAX_AGE:-2592000000}" \
pm2 start npm \
  --name "$backend_name" \
  --cwd "$platform_backend_dir" \
  -- \
  run dev

log "Starting platform frontend (PM2: $frontend_name)"
pm2_delete_if_exists "$frontend_name"
# Next dev + Turbopack expects this folder in some scenarios; it can disappear if
# a production `next build` runs in the same workspace. Creating it is harmless.
mkdir -p "$platform_frontend_dir/.next/static/development" >/dev/null 2>&1 || true
NEXT_PUBLIC_API_URL="${platform_url}/api/v1" \
NEXT_PUBLIC_WS_URL="$platform_url" \
NEXT_PUBLIC_DIRECTORY_URL="$directory_url" \
pm2 start npm \
  --name "$frontend_name" \
  --cwd "$platform_frontend_dir" \
  -- \
  run dev -- -p "$frontend_port"

log "Starting miners (PM2)"
idx=0
for hk in "${miner_hotkeys[@]}"; do
  miner_name="${pm2_prefix}-miner-${network}-${hk}"
  pm2_delete_if_exists "$miner_name"
  port="$((miner_axon_port_base + idx))"
  idx="$((idx + 1))"

  pm2 start "$venv_dir/bin/python" \
    --name "$miner_name" \
    --cwd "$repo_dir" \
    -- \
    "$repo_dir/neurons/miner.py" \
    --netuid "$netuid" \
    --wallet.name "$miner_wallet" \
    --wallet.hotkey "$hk" \
    --subtensor.network "$network" \
    --axon.port "$port" \
    --logging.debug
done

log "Starting validator (PM2: $validator_name)"
pm2_delete_if_exists "$validator_name"
POKER44_PROVIDER="platform" \
POKER44_PLATFORM_BACKEND_URL="$platform_url" \
POKER44_PLATFORM_PUBLIC_URL="$platform_url" \
POKER44_INTERNAL_EVAL_SECRET="$internal_eval_secret" \
POKER44_DIRECTORY_URL="$directory_url" \
POKER44_DIRECTORY_SHARED_SECRET="$directory_secret" \
POKER44_ANNOUNCE_INTERVAL_S="${POKER44_ANNOUNCE_INTERVAL_S:-2}" \
POKER44_AUTOSIMULATE="$autosimulate" \
POKER44_TASK_BATCH_SIZE="$task_batch_size" \
POKER44_QUERY_HOTKEYS="$miner_ss58_csv" \
POKER44_VALIDATOR_ID="$validator_ss58" \
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
# Health checks + smoke
# ---------------------------------------------------------------------------
log "Waiting for health endpoints"
wait_http "$platform_url/health/live" 90
wait_http "$directory_url/healthz" 30
wait_http "$frontend_url/poker-gameplay/p2p" 120

log "Running smoke checks"
POKER44_PLATFORM_BACKEND_URL="$platform_url" \
POKER44_INTERNAL_EVAL_SECRET="$internal_eval_secret" \
POKER44_VALIDATOR_ID="$validator_ss58" \
POKER44_DIRECTORY_URL="$directory_url" \
bash "$repo_dir/scripts/testnet/smoke_validator_stack.sh"

log "Up."
log "Open:"
log "  $frontend_url/poker-gameplay/p2p"
log "PM2:"
log "  pm2 ls | rg \"$pm2_prefix\""
log "  pm2 logs \"$validator_name\""
log "Down:"
log "  bash $repo_dir/scripts/deploy/pm2/down.sh"
