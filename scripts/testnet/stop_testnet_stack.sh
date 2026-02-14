#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../.." && pwd)"

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
    echo "[info] killing pid $pid ($pid_file)"
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

kill_if_running "$repo_dir/.testnet_validator.pid"

for pid_file in "$repo_dir"/.testnet_miner_*.pid; do
  [ -e "$pid_file" ] || continue
  kill_if_running "$pid_file"
done

echo "[info] stopping local p2p stack (best-effort)"
bash "$repo_dir/scripts/validator/p2p/stop.sh" || true

echo "[info] stopped (best-effort)"

