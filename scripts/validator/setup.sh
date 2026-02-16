#!/usr/bin/env bash
set -euo pipefail

# Validator operator convenience wrapper.
#
# This brings up the *per-validator* stack:
# - Platform backend (Node) + Postgres/Redis (docker compose)
# - Indexer read API (FastAPI)
# - Bittensor validator neuron (Python)
#
# Internally this wraps: scripts/deploy/pm2/up-validator-stack.sh

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../.." && pwd)"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v bash >/dev/null 2>&1 || die "bash not found"

# Defaults tuned for local / testnet iteration.
export NETUID="${NETUID:-401}"
export NETWORK="${NETWORK:-test}"
export VALIDATOR_WALLET="${VALIDATOR_WALLET:-poker44-test}"
export VALIDATOR_HOTKEY="${VALIDATOR_HOTKEY:-default}"

# Platform backend runtime secrets (override in env for production).
export INTERNAL_EVAL_SECRET="${INTERNAL_EVAL_SECRET:-dev-internal-eval-secret}"
export JWT_SECRET="${JWT_SECRET:-dev-jwt-secret-minimum-32-characters-long}"

# CORS origins for the platform backend (frontend usually runs elsewhere).
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}"

# Directory and ledger are "central" services; pass URLs if you want rooms to be discoverable / settled.
export POKER44_DIRECTORY_URL="${POKER44_DIRECTORY_URL:-${DIRECTORY_URL:-}}"
export LEDGER_API_URL="${LEDGER_API_URL:-}"

# If START_PORT isn't numeric, the underlying script chooses a random free port range.
export START_PORT="${START_PORT:-rand}"

# Prefix PM2 process names so multiple validators can coexist on one machine.
if [ -z "${PM2_PREFIX:-}" ]; then
  safe_wallet="$(echo "$VALIDATOR_WALLET" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_')"
  safe_hotkey="$(echo "$VALIDATOR_HOTKEY" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_')"
  export PM2_PREFIX="poker44-${safe_wallet:-wallet}-${safe_hotkey:-hotkey}"
fi

log "Bringing up validator stack (pm2)."
log "  network=$NETWORK netuid=$NETUID wallet=$VALIDATOR_WALLET hotkey=$VALIDATOR_HOTKEY"
log "  directory=${POKER44_DIRECTORY_URL:-<disabled>} ledger=${LEDGER_API_URL:-<disabled>}"
log "  start_port=$START_PORT pm2_prefix=$PM2_PREFIX"

exec bash "$repo_dir/scripts/deploy/pm2/up-validator-stack.sh"

