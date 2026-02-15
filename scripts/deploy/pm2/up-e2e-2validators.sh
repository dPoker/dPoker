#!/usr/bin/env bash
set -euo pipefail

# Start an end-to-end local stack with:
# - central: directory + ledger + frontend
# - 3 miners (testnet)
# - 2 validators (testnet), each with its own platform backend + DB + indexer
#
# One validator can be marked "dangerous" by setting INDEXER_TEE_ENABLED=false.
#
# Usage:
#   cd poker44-subnet
#   NETWORK=test NETUID=401 \
#   VALIDATOR_WALLET=poker44-test VALIDATOR1_HOTKEY=validator VALIDATOR2_HOTKEY=validator2 \
#   MINER_WALLET=owner MINER_HOTKEYS=miner1,miner2,miner3 \
#   START_PORT=random \
#   bash scripts/deploy/pm2/up-e2e-2validators.sh

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../../.." && pwd)"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v pm2 >/dev/null 2>&1 || die "pm2 not found"

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

# Bittensor (on-chain)
network="${NETWORK:-test}"
netuid="${NETUID:-401}"

validator_wallet="${VALIDATOR_WALLET:-poker44-test}"
validator1_hotkey="${VALIDATOR1_HOTKEY:-validator}"
validator2_hotkey="${VALIDATOR2_HOTKEY:-validator2}"

miner_wallet="${MINER_WALLET:-owner}"
miner_hotkeys_csv="${MINER_HOTKEYS:-miner1,miner2,miner3}"

# Shared secrets
directory_secret="${DIRECTORY_SHARED_SECRET:-dev-secret}"
internal_eval_secret="${INTERNAL_EVAL_SECRET:-dev-internal-eval-secret}"
jwt_secret="${JWT_SECRET:-dev-jwt-secret-minimum-32-characters-long}"

# Ports
base="$(pick_start_port)"
directory_port="$(find_free_port "$base")" || die "Failed to pick directory port"
ledger_port="$(find_free_port "$((directory_port + 1))")" || die "Failed to pick ledger port"
frontend_port="$(find_free_port "$((ledger_port + 1))")" || die "Failed to pick frontend port"

miner_axon_base="$(find_free_port "$((frontend_port + 200))" 2000)" || die "Failed to pick miner axon base port"

v1_backend_port="$(find_free_port "$((frontend_port + 400))")" || die "Failed to pick v1 backend port"
v1_indexer_port="$(find_free_port "$((v1_backend_port + 1))")" || die "Failed to pick v1 indexer port"
v1_postgres_port="$(find_free_port "$((v1_indexer_port + 200))")" || die "Failed to pick v1 postgres port"
v1_redis_port="$(find_free_port "$((v1_postgres_port + 1))")" || die "Failed to pick v1 redis port"

v2_backend_port="$(find_free_port "$((v1_redis_port + 200))")" || die "Failed to pick v2 backend port"
v2_indexer_port="$(find_free_port "$((v2_backend_port + 1))")" || die "Failed to pick v2 indexer port"
v2_postgres_port="$(find_free_port "$((v2_indexer_port + 200))")" || die "Failed to pick v2 postgres port"
v2_redis_port="$(find_free_port "$((v2_postgres_port + 1))")" || die "Failed to pick v2 redis port"

directory_url="http://127.0.0.1:${directory_port}"
ledger_api_url="http://127.0.0.1:${ledger_port}/api/v1"
frontend_url="http://127.0.0.1:${frontend_port}"

cors_origins="http://localhost:${frontend_port},http://127.0.0.1:${frontend_port}"

log "Chosen ports:"
log "  directory: $directory_port ($directory_url)"
log "  ledger:    $ledger_port ($ledger_api_url)"
log "  frontend:  $frontend_port ($frontend_url)"
log "  miners axon base: $miner_axon_base"
log "  v1 backend/indexer/db/redis: $v1_backend_port / $v1_indexer_port / $v1_postgres_port / $v1_redis_port"
log "  v2 backend/indexer/db/redis: $v2_backend_port / $v2_indexer_port / $v2_postgres_port / $v2_redis_port"

# Central: directory + frontend
PM2_PREFIX="${PM2_PREFIX_CENTRAL:-poker44-central}" \
DIRECTORY_PORT="$directory_port" \
FRONTEND_PORT="$frontend_port" \
DIRECTORY_SHARED_SECRET="$directory_secret" \
DIRECTORY_CORS_ORIGINS="*" \
NEXT_PUBLIC_LEDGER_API_URL="$ledger_api_url" \
bash "$repo_dir/scripts/deploy/pm2/up-central.sh"

# Central: ledger
PM2_PREFIX="${PM2_PREFIX_LEDGER:-poker44-ledger}" \
LEDGER_PORT="$ledger_port" \
LEDGER_DIRECTORY_URL="$directory_url" \
DIRECTORY_SHARED_SECRET="$directory_secret" \
JWT_SECRET="$jwt_secret" \
CORS_ORIGINS="$cors_origins" \
bash "$repo_dir/scripts/deploy/pm2/up-ledger.sh"

# Miners
PM2_PREFIX="${PM2_PREFIX_MINERS:-poker44-miners}" \
NETWORK="$network" NETUID="$netuid" \
MINER_WALLET="$miner_wallet" MINER_HOTKEYS="$miner_hotkeys_csv" \
MINER_AXON_PORT_BASE="$miner_axon_base" \
bash "$repo_dir/scripts/deploy/pm2/up-miners.sh"

# Validator 1 (attested)
PM2_PREFIX="${PM2_PREFIX_VALI1:-poker44-vali1}" \
NETWORK="$network" NETUID="$netuid" \
VALIDATOR_WALLET="$validator_wallet" VALIDATOR_HOTKEY="$validator1_hotkey" \
BACKEND_PORT="$v1_backend_port" INDEXER_PORT="$v1_indexer_port" \
POSTGRES_PORT="$v1_postgres_port" REDIS_PORT="$v1_redis_port" \
POSTGRES_DB="poker44_poker_${validator1_hotkey}" \
JWT_SECRET="$jwt_secret" \
LEDGER_API_URL="$ledger_api_url" \
CORS_ORIGINS="$cors_origins" \
POKER44_DIRECTORY_URL="$directory_url" \
DIRECTORY_SHARED_SECRET="$directory_secret" \
INTERNAL_EVAL_SECRET="$internal_eval_secret" \
POKER44_VALIDATOR_NAME="poker44-validator-1" \
INDEXER_TEE_ENABLED="true" \
POKER44_AUTOSIMULATE="true" \
bash "$repo_dir/scripts/deploy/pm2/up-validator-stack.sh"

# Validator 2 (dangerous)
PM2_PREFIX="${PM2_PREFIX_VALI2:-poker44-vali2}" \
NETWORK="$network" NETUID="$netuid" \
VALIDATOR_WALLET="$validator_wallet" VALIDATOR_HOTKEY="$validator2_hotkey" \
BACKEND_PORT="$v2_backend_port" INDEXER_PORT="$v2_indexer_port" \
POSTGRES_PORT="$v2_postgres_port" REDIS_PORT="$v2_redis_port" \
POSTGRES_DB="poker44_poker_${validator2_hotkey}" \
JWT_SECRET="$jwt_secret" \
LEDGER_API_URL="$ledger_api_url" \
CORS_ORIGINS="$cors_origins" \
POKER44_DIRECTORY_URL="$directory_url" \
DIRECTORY_SHARED_SECRET="$directory_secret" \
INTERNAL_EVAL_SECRET="$internal_eval_secret" \
POKER44_VALIDATOR_NAME="poker44-validator-2" \
INDEXER_TEE_ENABLED="${INDEXER_TEE_ENABLED_VALI2:-false}" \
POKER44_AUTOSIMULATE="true" \
bash "$repo_dir/scripts/deploy/pm2/up-validator-stack.sh"

log "Up."
log "Open:"
log "  $frontend_url/poker-gameplay"
log "Directory:"
log "  $directory_url/rooms"
log "Ledger:"
log "  $ledger_api_url"

