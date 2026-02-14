#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
poker44_dir="$(cd "$here/../../.." && pwd)"
# Default workspace layout:
#   <workspace>/poker44-subnet
#   <workspace>/platform/backend
platform_dir="${PLATFORM_BACKEND_DIR:-$poker44_dir/../platform/backend}"
platform_frontend_dir="${PLATFORM_FRONTEND_DIR:-$poker44_dir/../platform/frontend}"

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

kill_if_running "$poker44_dir/.mock_validator.pid"
kill_if_running "$poker44_dir/.room_directory.pid"
kill_if_running "$platform_dir/.platform_backend.pid"
kill_if_running "$platform_frontend_dir/.platform_frontend.pid"

echo "[info] stopped (best-effort)"
