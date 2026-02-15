#!/usr/bin/env bash
set -euo pipefail

# Start one or more Bittensor miners under PM2.
#
# Usage:
#   cd poker44-subnet
#   NETWORK=test NETUID=401 \
#   MINER_WALLET=owner MINER_HOTKEYS=miner1,miner2,miner3 \
#   MINER_AXON_PORT_BASE=9101 \
#   bash scripts/deploy/pm2/up-miners.sh

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../../.." && pwd)"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v pm2 >/dev/null 2>&1 || die "pm2 not found"

netuid="${NETUID:-401}"
network="${NETWORK:-test}"

pm2_prefix="${PM2_PREFIX:-poker44-miners}"
miner_wallet="${MINER_WALLET:-owner}"
miner_hotkeys_csv="${MINER_HOTKEYS:-miner1}"
axon_port_base="${MINER_AXON_PORT_BASE:-9101}"

venv_dir="${VENV_DIR:-$repo_dir/validator_env}"

log "Preparing python venv (miners): $venv_dir"
if [ ! -d "$venv_dir" ]; then
  python3 -m venv "$venv_dir"
fi

log "Installing subnet python deps (best-effort idempotent)"
"$venv_dir/bin/python" -m pip install --upgrade pip wheel "setuptools~=70.0" >/dev/null
"$venv_dir/bin/python" -m pip install -r "$repo_dir/requirements.txt" >/dev/null
"$venv_dir/bin/python" -m pip install -e "$repo_dir" >/dev/null

pm2_delete_if_exists() {
  local name="$1"
  pm2 delete "$name" >/dev/null 2>&1 || true
}

idx=0
IFS=',' read -ra hotkeys <<<"$miner_hotkeys_csv"
for hk in "${hotkeys[@]}"; do
  hk="$(echo "$hk" | xargs)"
  [ -n "$hk" ] || continue

  name="${pm2_prefix}-miner-${network}-${hk}"
  port="$((axon_port_base + idx))"
  idx=$((idx + 1))

  log "Starting miner $miner_wallet/$hk on axon.port=$port (PM2: $name)"
  pm2_delete_if_exists "$name"
  pm2 start "$venv_dir/bin/python" \
    --name "$name" \
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

pm2 save >/dev/null 2>&1 || true
log "Up."

