#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dpoker_dir="$(cd "$here/../../.." && pwd)"
platform_dir="${PLATFORM_BACKEND_DIR:-$dpoker_dir/../poker44-platform-backend}"

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

kill_if_running "$dpoker_dir/.mock_validator.pid"
kill_if_running "$dpoker_dir/.room_directory.pid"
kill_if_running "$platform_dir/.platform_backend.pid"

echo "[info] stopped (best-effort)"

