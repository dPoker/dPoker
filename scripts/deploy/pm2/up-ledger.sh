#!/usr/bin/env bash
set -euo pipefail

# Deploy the central Ledger/Auth service under PM2.
# This is the custody + sessions + bankroll source-of-truth (simulated chips).
#
# It runs the platform backend in "ledger mode" (same codebase, separate DB/Redis).
#
# Usage:
#   cd poker44-subnet
#   PM2_PREFIX=poker44-ledger \
#   START_PORT=7001 \
#   LEDGER_DIRECTORY_URL=http://127.0.0.1:8010 \
#   bash scripts/deploy/pm2/up-ledger.sh

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../../.." && pwd)"

# Default workspace layout:
#   <workspace>/poker44-subnet
#   <workspace>/platform/backend
platform_backend_dir="${PLATFORM_BACKEND_DIR:-$repo_dir/../platform/backend}"

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

pm2_prefix="${PM2_PREFIX:-poker44-ledger}"
backend_name="${pm2_prefix}-backend"

start_port="$(pick_start_port)"
ledger_port="${LEDGER_PORT:-}"
if [[ -z "$ledger_port" ]]; then
  ledger_port="$(find_free_port "$start_port")" || die "Failed to find a free ledger port near $start_port"
fi

compose_project="${COMPOSE_PROJECT_NAME:-$pm2_prefix}"
postgres_port="${POSTGRES_PORT:-}"
redis_port="${REDIS_PORT:-}"
if [[ -z "$postgres_port" ]]; then
  postgres_port="$(find_free_port "$((ledger_port + 200))")" || die "Failed to find a free Postgres port"
fi
if [[ -z "$redis_port" ]]; then
  redis_port="$(find_free_port "$((postgres_port + 1))")" || die "Failed to find a free Redis port"
fi

postgres_user="${POSTGRES_USER:-poker44}"
postgres_password="${POSTGRES_PASSWORD:-poker44_local_pwd}"
postgres_db="${POSTGRES_DB:-poker44_ledger}"
database_url="postgresql://${postgres_user}:${postgres_password}@localhost:${postgres_port}/${postgres_db}"
redis_url="redis://localhost:${redis_port}"

jwt_secret="${JWT_SECRET:-dev-jwt-secret-minimum-32-characters-long}"
cors_origins="${CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}"
directory_url="${LEDGER_DIRECTORY_URL:-${POKER44_DIRECTORY_URL:-}}"
directory_url="${directory_url%/}"

log "Repo: $repo_dir"
log "Platform backend: $platform_backend_dir"
log "Ledger base URL: http://127.0.0.1:${ledger_port}"
log "Directory URL: ${directory_url:-<disabled>}"
log "Compose project: $compose_project"
log "Postgres: port=$postgres_port db=$postgres_db"
log "Redis:    port=$redis_port"

[ -d "$platform_backend_dir" ] || die "Platform backend dir not found: $platform_backend_dir"
cd "$platform_backend_dir"
if [ ! -f .env ]; then
  cp .env.example .env
fi
if [ ! -d node_modules ]; then
  npm install
fi

log "Starting Postgres+Redis via docker compose (ledger)"
COMPOSE_PROJECT_NAME="$compose_project" \
POSTGRES_PORT="$postgres_port" \
REDIS_PORT="$redis_port" \
POSTGRES_USER="$postgres_user" \
POSTGRES_PASSWORD="$postgres_password" \
POSTGRES_DB="$postgres_db" \
npm run docker:up

log "Waiting for Postgres/Redis health (ledger)"
deadline="$(( $(date +%s) + 90 ))"
while true; do
  if COMPOSE_PROJECT_NAME="$compose_project" docker compose exec -T postgres \
    pg_isready -U "$postgres_user" -d "$postgres_db" >/dev/null 2>&1 \
    && COMPOSE_PROJECT_NAME="$compose_project" docker compose exec -T redis \
    redis-cli ping >/dev/null 2>&1; then
    break
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    die "timeout waiting for Postgres/Redis for ledger (project=$compose_project)"
  fi
  sleep 1
done

log "Running migrations (ledger)"
DATABASE_URL="$database_url" \
npm run migration:run:dev

log "Starting ledger backend (PM2: $backend_name)"
pm2_delete_if_exists "$backend_name"
PORT="$ledger_port" \
DATABASE_URL="$database_url" \
REDIS_URL="$redis_url" \
CORS_ORIGINS="$cors_origins" \
JWT_SECRET="$jwt_secret" \
JWT_EXPIRES_IN="${JWT_EXPIRES_IN:-30d}" \
COOKIE_MAX_AGE="${COOKIE_MAX_AGE:-2592000000}" \
AUTH_RETURN_TOKEN_IN_BODY="true" \
AUTH_SET_COOKIE="false" \
	LEDGER_DIRECTORY_URL="$directory_url" \
	LEDGER_MIN_INDEXERS="${LEDGER_MIN_INDEXERS:-2}" \
	LEDGER_MIN_VALIDATOR_STAKE="${LEDGER_MIN_VALIDATOR_STAKE:-0}" \
	LEDGER_VALIDATOR_BLACKLIST="${LEDGER_VALIDATOR_BLACKLIST:-}" \
	SETTLEMENT_API_ENABLED="${SETTLEMENT_API_ENABLED:-true}" \
	pm2 start npm \
	  --name "$backend_name" \
	  --cwd "$platform_backend_dir" \
	  -- \
	  run dev

log "Waiting for ledger health"
wait_http "http://127.0.0.1:${ledger_port}/health/live" 90

pm2 save >/dev/null 2>&1 || true

log "Up."
log "Ledger:"
log "  http://127.0.0.1:${ledger_port}"
log "  API: http://127.0.0.1:${ledger_port}/api/v1"
