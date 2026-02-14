#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../.." && pwd)"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v node >/dev/null 2>&1 || die "node not found"
command -v npm >/dev/null 2>&1 || die "npm not found"
command -v docker >/dev/null 2>&1 || die "docker not found"

# Bittensor
netuid="${NETUID:-401}"
network="${NETWORK:-test}"

validator_wallet="${VALIDATOR_WALLET:-poker44-test}"
validator_hotkey="${VALIDATOR_HOTKEY:-default}"

miner_wallet="${MINER_WALLET:-owner}"
miner_hotkeys_csv="${MINER_HOTKEYS:-miner1,miner2,miner3}"
miner_port_base="${MINER_AXON_PORT_BASE:-9101}"

register_miners="${REGISTER_MINERS:-false}"

# Local stack (platform + directory)
directory_port="${DIRECTORY_PORT:-8010}"
directory_secret="${DIRECTORY_SHARED_SECRET:-dev-secret}"
platform_url="${PLATFORM_URL:-http://127.0.0.1:3001}"
internal_eval_secret="${INTERNAL_EVAL_SECRET:-dev-internal-eval-secret}"
start_frontend="${START_FRONTEND:-true}"
frontend_port="${FRONTEND_PORT:-3000}"

# Validator P2P settings
export POKER44_PROVIDER="platform"
export POKER44_PLATFORM_BACKEND_URL="$platform_url"
export POKER44_INTERNAL_EVAL_SECRET="$internal_eval_secret"
export POKER44_DIRECTORY_URL="http://127.0.0.1:$directory_port"
export POKER44_DIRECTORY_SHARED_SECRET="$directory_secret"
export POKER44_ANNOUNCE_INTERVAL_S="${POKER44_ANNOUNCE_INTERVAL_S:-2}"
export POKER44_AUTOSIMULATE="${POKER44_AUTOSIMULATE:-true}"
export POKER44_TASK_BATCH_SIZE="${POKER44_TASK_BATCH_SIZE:-10}"
export POKER44_QUERY_SAMPLE_SIZE="${POKER44_QUERY_SAMPLE_SIZE:-20}"

poll_interval_s="${POLL_INTERVAL_S:-10}"
epoch_length="${EPOCH_LENGTH:-20}"

log "Starting local P2P stack (directory + platform + optional frontend)"
RUN_MOCK_VALIDATOR="false" \
  DIRECTORY_PORT="$directory_port" \
  DIRECTORY_SHARED_SECRET="$directory_secret" \
  PLATFORM_URL="$platform_url" \
  INTERNAL_EVAL_SECRET="$internal_eval_secret" \
  START_FRONTEND="$start_frontend" \
  FRONTEND_PORT="$frontend_port" \
  bash "$repo_dir/scripts/validator/p2p/setup.sh"

venv_dir="${VENV_DIR:-$repo_dir/validator_env}"
[ -d "$venv_dir" ] || die "Venv dir not found: $venv_dir (did p2p setup succeed?)"
source "$venv_dir/bin/activate"

validator_ss58="$(python - <<PY
import bittensor as bt
w=bt.Wallet(name="$validator_wallet", hotkey="$validator_hotkey")
print(w.hotkey.ss58_address)
PY
)"
[ -n "$validator_ss58" ] || die "Failed to compute validator hotkey ss58"
export POKER44_VALIDATOR_ID="${POKER44_VALIDATOR_ID:-$validator_ss58}"

log "Validator hotkey: $validator_ss58"

parse_hotkeys() {
  local csv="$1"
  python - <<'PY' "$csv"
import sys
csv=sys.argv[1]
items=[x.strip() for x in csv.split(",") if x.strip()]
print("\n".join(items))
PY
}

check_registered() {
  local wallet_name="$1"
  local hotkey_name="$2"
  python - <<PY
import bittensor as bt
sub=bt.Subtensor(network="$network")
w=bt.Wallet(name="$wallet_name", hotkey="$hotkey_name")
print("true" if sub.is_hotkey_registered(netuid=int("$netuid"), hotkey_ss58=w.hotkey.ss58_address) else "false")
PY
}

maybe_register() {
  local wallet_name="$1"
  local hotkey_name="$2"
  python - <<PY
import bittensor as bt
netuid=int("$netuid")
sub=bt.Subtensor(network="$network")
w=bt.Wallet(name="$wallet_name", hotkey="$hotkey_name")
addr=w.hotkey.ss58_address
if sub.is_hotkey_registered(netuid=netuid, hotkey_ss58=addr):
    print("already_registered")
    raise SystemExit(0)
print(f"registering {wallet_name}/{hotkey_name} ({addr}) on netuid={netuid} network={sub.network} ...")
resp=sub.register(wallet=w, netuid=netuid, max_allowed_attempts=3, cuda=False, wait_for_inclusion=True, wait_for_finalization=True, raise_error=True)
print(resp)
PY
}

miner_hotkeys=()
while IFS= read -r hk; do
  [ -n "$hk" ] || continue
  miner_hotkeys+=("$hk")
done < <(parse_hotkeys "$miner_hotkeys_csv")

if [ "${#miner_hotkeys[@]}" -eq 0 ]; then
  die "MINER_HOTKEYS is empty"
fi

registered_count=0
for hk in "${miner_hotkeys[@]}"; do
  ok="$(check_registered "$miner_wallet" "$hk")"
  if [ "$ok" = "true" ]; then
    registered_count=$((registered_count + 1))
  fi
done

if [ "$registered_count" -eq 0 ]; then
  if [ "${register_miners,,}" = "true" ]; then
    log "No miners registered yet. Attempting registration (will prompt for wallet password if encrypted)."
    for hk in "${miner_hotkeys[@]}"; do
      ok="$(check_registered "$miner_wallet" "$hk")"
      if [ "$ok" != "true" ]; then
        maybe_register "$miner_wallet" "$hk" || true
      fi
    done
  else
    die "No miners are registered on netuid=$netuid (NETWORK=$network). Set REGISTER_MINERS=true to register them."
  fi
fi

# Re-count.
registered_count=0
for hk in "${miner_hotkeys[@]}"; do
  ok="$(check_registered "$miner_wallet" "$hk")"
  if [ "$ok" = "true" ]; then
    registered_count=$((registered_count + 1))
  fi
done
if [ "$registered_count" -eq 0 ]; then
  die "No registered miners found after registration attempt. Aborting."
fi

# Build list of miner hotkey ss58 addresses for validator query targeting.
miner_ss58_csv="$(python - <<PY
import bittensor as bt
sub=bt.Subtensor(network="$network")
netuid=int("$netuid")
out=[]
for hk in "$miner_hotkeys_csv".split(","):
    hk=hk.strip()
    if not hk:
        continue
    w=bt.Wallet(name="$miner_wallet", hotkey=hk)
    addr=w.hotkey.ss58_address
    if sub.is_hotkey_registered(netuid=netuid, hotkey_ss58=addr):
        out.append(addr)
print(",".join(out))
PY
)"
if [ -n "$miner_ss58_csv" ]; then
  export POKER44_QUERY_HOTKEYS="$miner_ss58_csv"
  log "Validator will target miners: $miner_ss58_csv"
else
  log "Warning: no registered miner hotkeys resolved for targeting; validator will fall back to sampling."
fi

kill_if_running() {
  local pid_file="$1"
  if [ ! -f "$pid_file" ]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file" || true)"
  if [ -z "$pid" ]; then
    rm -f "$pid_file"
    return 0
  fi
  if kill -0 "$pid" 2>/dev/null; then
    log "killing pid $pid ($pid_file)"
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

log "Starting registered miners (Bittensor testnet)"
idx=0
for hk in "${miner_hotkeys[@]}"; do
  ok="$(check_registered "$miner_wallet" "$hk")"
  if [ "$ok" != "true" ]; then
    log "Skipping unregistered miner: $miner_wallet/$hk"
    continue
  fi

  port="$((miner_port_base + idx))"
  idx=$((idx + 1))

  pid_file="$repo_dir/.testnet_miner_${hk}.pid"
  log_file="$repo_dir/.testnet_miner_${hk}.log"
  kill_if_running "$pid_file"

  log "Starting miner $miner_wallet/$hk on axon.port=$port"
  nohup python "$repo_dir/neurons/miner.py" \
    --netuid "$netuid" \
    --wallet.name "$miner_wallet" \
    --wallet.hotkey "$hk" \
    --subtensor.network "$network" \
    --axon.port "$port" \
    --logging.debug \
    >"$log_file" 2>&1 &
  pid=$!
  echo "$pid" >"$pid_file"
  log "Miner pid: $pid (log: $log_file)"
done

log "Starting validator (Bittensor testnet)"
validator_pid_file="$repo_dir/.testnet_validator.pid"
validator_log_file="$repo_dir/.testnet_validator.log"
kill_if_running "$validator_pid_file"

nohup python "$repo_dir/neurons/validator.py" \
  --netuid "$netuid" \
  --wallet.name "$validator_wallet" \
  --wallet.hotkey "$validator_hotkey" \
  --subtensor.network "$network" \
  --neuron.axon_off \
  --poll_interval_seconds "$poll_interval_s" \
  --neuron.epoch_length "$epoch_length" \
  --logging.debug \
  >"$validator_log_file" 2>&1 &
validator_pid=$!
echo "$validator_pid" >"$validator_pid_file"
log "Validator pid: $validator_pid (log: $validator_log_file)"

log "Running smoke checks"
POKER44_PLATFORM_BACKEND_URL="$platform_url" \
  POKER44_INTERNAL_EVAL_SECRET="$internal_eval_secret" \
  POKER44_VALIDATOR_ID="$POKER44_VALIDATOR_ID" \
  POKER44_DIRECTORY_URL="http://127.0.0.1:$directory_port" \
  bash "$repo_dir/scripts/testnet/smoke_validator_stack.sh"

log "Testnet stack is up."
log "Tail logs:"
log "  validator: tail -f $validator_log_file"
log "  miner1:    tail -f $repo_dir/.testnet_miner_miner1.log"
log "Stop:"
log "  bash $repo_dir/scripts/testnet/stop_testnet_stack.sh"

