#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
poker44_dir="$(cd "$here/../../.." && pwd)"
# Default workspace layout:
#   <workspace>/poker44-subnet
#   <workspace>/platform/backend
platform_dir="${PLATFORM_BACKEND_DIR:-$poker44_dir/../platform/backend}"
platform_frontend_dir="${PLATFORM_FRONTEND_DIR:-$poker44_dir/../platform/frontend}"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v node >/dev/null 2>&1 || die "node not found"
command -v npm >/dev/null 2>&1 || die "npm not found"
command -v docker >/dev/null 2>&1 || die "docker not found"

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

venv_dir="${VENV_DIR:-$poker44_dir/validator_env}"
directory_port="${DIRECTORY_PORT:-8010}"
directory_secret="${DIRECTORY_SHARED_SECRET:-dev-secret}"

platform_url="${PLATFORM_URL:-http://127.0.0.1:3001}"
eval_secret="${INTERNAL_EVAL_SECRET:-dev-internal-eval-secret}"
start_frontend="${START_FRONTEND:-true}"

frontend_port="${FRONTEND_PORT:-3000}"
frontend_url="http://127.0.0.1:${frontend_port}"
if [ "${start_frontend,,}" != "false" ]; then
  if port_in_use "$frontend_port"; then
    log "Port $frontend_port is already in use. Picking a free port for the frontend..."
    for cand in 3002 3003 3004 3005 3006 3007 3008 3009 3010; do
      if ! port_in_use "$cand"; then
        frontend_port="$cand"
        break
      fi
    done
  fi
  frontend_url="http://127.0.0.1:${frontend_port}"
fi

validator_id="${VALIDATOR_ID:-vali-$(hostname -s 2>/dev/null || hostname)}"

log "poker44 dir: $poker44_dir"
log "Platform backend dir: $platform_dir"
log "Platform frontend dir: $platform_frontend_dir"
log "Validator id: $validator_id"

log "Creating python venv (if needed): $venv_dir"
if [ ! -d "$venv_dir" ]; then
  python3 -m venv "$venv_dir"
fi
source "$venv_dir/bin/activate"

log "Installing subnet python deps"
python -m pip install --upgrade pip wheel "setuptools~=70.0"
python -m pip install -r "$poker44_dir/requirements.txt"
python -m pip install -e "$poker44_dir"

log "Starting room directory on :$directory_port"
export DIRECTORY_SHARED_SECRET="$directory_secret"
export DIRECTORY_TTL_SECONDS="${DIRECTORY_TTL_SECONDS:-60}"
nohup python -m uvicorn poker44.p2p.room_directory.app:app \
  --host 127.0.0.1 --port "$directory_port" \
  >"$poker44_dir/.room_directory.log" 2>&1 &
directory_pid=$!
echo "$directory_pid" >"$poker44_dir/.room_directory.pid"
log "Room directory pid: $directory_pid (log: $poker44_dir/.room_directory.log)"

log "Preparing platform backend (.env, docker, migrations)"
[ -d "$platform_dir" ] || die "Platform backend dir not found: $platform_dir"
cd "$platform_dir"

if [ ! -f .env ]; then
  log "Creating platform .env from .env.example"
  cp .env.example .env
fi

# Ensure INTERNAL_EVAL_SECRET is set for internal endpoints.
if grep -q "^INTERNAL_EVAL_SECRET=" .env 2>/dev/null; then
  current_secret="$(grep -E "^INTERNAL_EVAL_SECRET=" .env | head -n1 | cut -d= -f2-)"
  if [ "$current_secret" != "$eval_secret" ]; then
    log "Updating INTERNAL_EVAL_SECRET in platform .env for local stack"
    sed -i "s|^INTERNAL_EVAL_SECRET=.*|INTERNAL_EVAL_SECRET=$eval_secret|" .env
  fi
else
  echo "INTERNAL_EVAL_SECRET=$eval_secret" >> .env
fi

# Ensure CORS allows the local frontend origin (including dynamic ports).
if [ "${start_frontend,,}" != "false" ]; then
  frontend_origin_localhost="http://localhost:$frontend_port"
  frontend_origin_ip="http://127.0.0.1:$frontend_port"
  if grep -q "^CORS_ORIGINS=" .env 2>/dev/null; then
    current_cors="$(grep -E "^CORS_ORIGINS=" .env | head -n1 | cut -d= -f2-)"
    updated_cors="$current_cors"

    if [[ ",$updated_cors," != *",$frontend_origin_localhost,"* ]]; then
      updated_cors="${updated_cors},${frontend_origin_localhost}"
    fi
    if [[ ",$updated_cors," != *",$frontend_origin_ip,"* ]]; then
      updated_cors="${updated_cors},${frontend_origin_ip}"
    fi

    if [ "$updated_cors" != "$current_cors" ]; then
      log "Updating CORS_ORIGINS in platform .env for local stack"
      sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=$updated_cors|" .env
    fi
  else
    echo "CORS_ORIGINS=$frontend_origin_localhost,$frontend_origin_ip" >> .env
  fi
fi

# Keep DATABASE_URL aligned with the repo's docker-compose defaults.
default_db_url="postgresql://poker44:poker44_local_pwd@localhost:55433/poker44_poker"
if grep -q "^DATABASE_URL=" .env 2>/dev/null; then
  current_db_url="$(grep -E "^DATABASE_URL=" .env | head -n1 | cut -d= -f2-)"
  if [ "$current_db_url" != "$default_db_url" ]; then
    log "Updating DATABASE_URL in platform .env for local stack"
    # NOTE: avoid perl replacement here because perl interpolates `@host` as an array.
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$default_db_url|" .env
  fi
else
  echo "DATABASE_URL=$default_db_url" >> .env
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

cd "$poker44_dir"

if [ "${start_frontend,,}" != "false" ]; then
  log "Preparing platform frontend (.env.local)"
  [ -d "$platform_frontend_dir" ] || die "Platform frontend dir not found: $platform_frontend_dir"
  cd "$platform_frontend_dir"

  if [ ! -f .env.local ]; then
    log "Creating frontend .env.local from .env.example"
    cp .env.example .env.local
  fi

  log "Installing platform frontend deps (npm)"
  npm install

  log "Starting platform frontend dev server on :$frontend_port"
  export PORT="$frontend_port"
  nohup npm run dev >"$platform_frontend_dir/.platform_frontend.log" 2>&1 &
  frontend_pid=$!
  echo "$frontend_pid" >"$platform_frontend_dir/.platform_frontend.pid"
  log "Platform frontend pid: $frontend_pid (log: $platform_frontend_dir/.platform_frontend.log)"

  log "Waiting for frontend health"
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
wait("$frontend_url", 90)
wait("$frontend_url/poker-gameplay/p2p", 90)
print("ok")
PY

  cd "$poker44_dir"
fi

run_mock="${RUN_MOCK_VALIDATOR:-true}"
if [ "${run_mock,,}" != "false" ]; then
  log "Running validator self-check + mock evaluation cycle (and announcing room)"
  # New env vars (preferred)
  export POKER44_PROVIDER="platform"
  export POKER44_PLATFORM_BACKEND_URL="$platform_url"
  export POKER44_INTERNAL_EVAL_SECRET="$eval_secret"
  export POKER44_DIRECTORY_URL="http://127.0.0.1:$directory_port"
  export POKER44_DIRECTORY_SHARED_SECRET="$directory_secret"
  export POKER44_VALIDATOR_ID="$validator_id"
  export POKER44_ANNOUNCE_INTERVAL_S="${POKER44_ANNOUNCE_INTERVAL_S:-2}"
  export POKER44_MOCK_MINERS="${POKER44_MOCK_MINERS:-2}"
  export POKER44_REWARD_WINDOW="${POKER44_REWARD_WINDOW:-1}"

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
    export POKER44_RUN_FOREVER="true"
    export POKER44_POLL_INTERVAL_S="${POKER44_POLL_INTERVAL_S:-10}"
    nohup python scripts/validator/p2p/run_mock_validator.py >"$poker44_dir/.mock_validator.log" 2>&1 &
    mock_validator_pid=$!
    echo "$mock_validator_pid" >"$poker44_dir/.mock_validator.pid"
    log "Mock validator pid: $mock_validator_pid (log: $poker44_dir/.mock_validator.log)"
  fi
fi

log "Setup complete."
log "Tail logs:"
log "  platform:  tail -f $platform_dir/.platform_backend.log"
log "  directory: tail -f $poker44_dir/.room_directory.log"
log "  validator:  tail -f $poker44_dir/.mock_validator.log"
if [ "${start_frontend,,}" != "false" ]; then
  log "  frontend:  tail -f $platform_frontend_dir/.platform_frontend.log"
  log "Open:"
  log "  $frontend_url/poker-gameplay/p2p"
fi
