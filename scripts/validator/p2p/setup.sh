#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dpoker_dir="$(cd "$here/../../.." && pwd)"
platform_dir="${PLATFORM_BACKEND_DIR:-$dpoker_dir/../poker44-platform-backend}"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v node >/dev/null 2>&1 || die "node not found"
command -v npm >/dev/null 2>&1 || die "npm not found"
command -v docker >/dev/null 2>&1 || die "docker not found"

venv_dir="${VENV_DIR:-$dpoker_dir/validator_env}"
directory_port="${DIRECTORY_PORT:-8010}"
directory_secret="${DIRECTORY_SHARED_SECRET:-dev-secret}"

platform_url="${PLATFORM_URL:-http://127.0.0.1:3001}"
eval_secret="${INTERNAL_EVAL_SECRET:-dev-internal-eval-secret}"

validator_id="${VALIDATOR_ID:-vali-$(hostname -s 2>/dev/null || hostname)}"

log "dPoker dir: $dpoker_dir"
log "Platform backend dir: $platform_dir"
log "Validator id: $validator_id"

log "Creating python venv (if needed): $venv_dir"
if [ ! -d "$venv_dir" ]; then
  python3 -m venv "$venv_dir"
fi
source "$venv_dir/bin/activate"

log "Installing dPoker python deps"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r "$dpoker_dir/requirements.txt"
python -m pip install -e "$dpoker_dir"

log "Starting room directory on :$directory_port"
export DIRECTORY_SHARED_SECRET="$directory_secret"
export DIRECTORY_TTL_SECONDS="${DIRECTORY_TTL_SECONDS:-60}"
nohup python -m uvicorn Aceguard.p2p.room_directory.app:app \
  --host 127.0.0.1 --port "$directory_port" \
  >"$dpoker_dir/.room_directory.log" 2>&1 &
directory_pid=$!
echo "$directory_pid" >"$dpoker_dir/.room_directory.pid"
log "Room directory pid: $directory_pid (log: $dpoker_dir/.room_directory.log)"

log "Preparing platform backend (.env, docker, migrations)"
[ -d "$platform_dir" ] || die "Platform backend dir not found: $platform_dir"
cd "$platform_dir"

if [ ! -f .env ]; then
  log "Creating platform .env from .env.example"
  cp .env.example .env
fi

# Ensure INTERNAL_EVAL_SECRET is set for internal endpoints.
if ! grep -q "^INTERNAL_EVAL_SECRET=" .env 2>/dev/null; then
  echo "INTERNAL_EVAL_SECRET=$eval_secret" >> .env
fi

log "Installing platform backend deps (npm)"
npm install

log "Starting Postgres+Redis via docker compose"
npm run docker:up

log "Running platform migrations"
npm run migration:run:dev

log "Starting platform backend dev server"
nohup npm run dev >"$platform_dir/.platform_backend.log" 2>&1 &
platform_pid=$!
echo "$platform_pid" >"$platform_dir/.platform_backend.pid"
log "Platform backend pid: $platform_pid (log: $platform_dir/.platform_backend.log)"

log "Waiting for platform + directory health"
python - <<PY
import time, requests
def wait(url, timeout=60):
  dl=time.time()+timeout
  while time.time()<dl:
    try:
      r=requests.get(url, timeout=2)
      if r.status_code==200:
        return
    except Exception:
      pass
    time.sleep(0.2)
  raise SystemExit(f"timeout waiting for {url}")
wait("$platform_url/health/live", 90)
wait("http://127.0.0.1:$directory_port/healthz", 30)
print("ok")
PY

cd "$dpoker_dir"

log "Running validator self-check + mock evaluation cycle (and announcing room)"
export ACEGUARD_PROVIDER="platform"
export ACEGUARD_PLATFORM_BACKEND_URL="$platform_url"
export ACEGUARD_INTERNAL_EVAL_SECRET="$eval_secret"
export ACEGUARD_DIRECTORY_URL="http://127.0.0.1:$directory_port"
export ACEGUARD_DIRECTORY_SHARED_SECRET="$directory_secret"
export ACEGUARD_VALIDATOR_ID="$validator_id"
export ACEGUARD_ANNOUNCE_INTERVAL_S="${ACEGUARD_ANNOUNCE_INTERVAL_S:-2}"
export ACEGUARD_MOCK_MINERS="${ACEGUARD_MOCK_MINERS:-2}"
export ACEGUARD_REWARD_WINDOW="${ACEGUARD_REWARD_WINDOW:-1}"

python scripts/validator/p2p/run_mock_validator.py

log "Directory rooms listing:"
python - <<PY
import requests, json
rooms=requests.get("http://127.0.0.1:$directory_port/rooms", timeout=5).json()
print(json.dumps(rooms, indent=2))
PY

start_daemon="${START_DAEMON:-true}"
if [ "${start_daemon,,}" != "false" ]; then
  log "Starting mock validator daemon (periodic announce + eval cycles)"
  export ACEGUARD_RUN_FOREVER="true"
  export ACEGUARD_POLL_INTERVAL_S="${ACEGUARD_POLL_INTERVAL_S:-10}"
  nohup python scripts/validator/p2p/run_mock_validator.py >"$dpoker_dir/.mock_validator.log" 2>&1 &
  mock_validator_pid=$!
  echo "$mock_validator_pid" >"$dpoker_dir/.mock_validator.pid"
  log "Mock validator pid: $mock_validator_pid (log: $dpoker_dir/.mock_validator.log)"
fi

log "Setup complete."
log "Tail logs:"
log "  platform:  tail -f $platform_dir/.platform_backend.log"
log "  directory: tail -f $dpoker_dir/.room_directory.log"
log "  validator:  tail -f $dpoker_dir/.mock_validator.log"
