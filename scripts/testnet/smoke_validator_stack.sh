#!/usr/bin/env bash
set -euo pipefail

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v curl >/dev/null 2>&1 || die "curl not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found"

platform_url="${POKER44_PLATFORM_BACKEND_URL:-http://127.0.0.1:3001}"
secret="${POKER44_INTERNAL_EVAL_SECRET:-}"
validator_id="${POKER44_VALIDATOR_ID:-}"

directory_url="${POKER44_DIRECTORY_URL:-}"
directory_url="${directory_url%/}"

[ -n "$secret" ] || die "POKER44_INTERNAL_EVAL_SECRET not set"

log "Platform: $platform_url"
log "Directory: ${directory_url:-<disabled>}"

log "Checking platform health"
curl -sf "$platform_url/health/live" >/dev/null

log "Checking internal eval health"
curl -sf -H "x-eval-secret: $secret" "$platform_url/internal/eval/health" >/dev/null

log "Ensuring a discoverable room exists"
if [ -n "$validator_id" ]; then
  ensure_body="$(printf '{"validatorId":"%s"}' "$validator_id")"
else
  ensure_body="{}"
fi
ensure_json="$(curl -sf -X POST \
  -H "content-type: application/json" \
  -H "x-eval-secret: $secret" \
  -d "$ensure_body" \
  "$platform_url/internal/rooms/ensure")"

room_code="$(python3 - <<'PY'
import json,sys
data=json.load(sys.stdin)
room=((data.get("data") or {}) if isinstance(data, dict) else {}).get("roomCode")
print(room or "")
PY
<<<"$ensure_json")"

log "Room code: ${room_code:-<none>}"

log "Simulating a mixed table (generates fresh hands)"
curl -sf -X POST \
  -H "content-type: application/json" \
  -H "x-eval-secret: $secret" \
  -d '{"humans":2,"bots":2,"hands":2}' \
  "$platform_url/internal/eval/simulate" >/dev/null

log "Fetching consume-once batches"
next_json="$(curl -sf -H "x-eval-secret: $secret" \
  "$platform_url/internal/eval/next?limit=3&requireMixed=true")"

batch_count="$(python3 - <<'PY'
import json,sys
data=json.load(sys.stdin)
batches=(((data.get("data") or {}) if isinstance(data, dict) else {}).get("batches") or [])
print(len(batches) if isinstance(batches, list) else 0)
PY
<<<"$next_json")"

log "Batches returned: $batch_count"
[ "$batch_count" -ge 1 ] || die "Expected at least 1 batch from /internal/eval/next"

if [ -n "$directory_url" ]; then
  log "Checking directory health"
  curl -sf "$directory_url/healthz" >/dev/null

  log "Checking directory rooms listing"
  if [ -n "$validator_id" ]; then
    # Announcements are async; give the validator a moment to publish.
    deadline="$(( $(date +%s) + 45 ))"
    while true; do
      rooms_json="$(curl -sf "$directory_url/rooms")"
      listed="$(python3 - <<'PY'
import json,sys
validator_id=sys.argv[1]
rooms=json.load(sys.stdin)
ok=False
if isinstance(rooms, list):
  for r in rooms:
    if isinstance(r, dict) and r.get("validator_id")==validator_id:
      ok=True
      break
print("true" if ok else "false")
PY
"$validator_id" <<<"$rooms_json")"

      if [ "$listed" = "true" ]; then
        log "Directory lists validator_id=$validator_id"
        break
      fi
      now="$(date +%s)"
      if [ "$now" -ge "$deadline" ]; then
        die "Directory does not list this validator_id yet (POKER44_VALIDATOR_ID=$validator_id)"
      fi
      sleep 0.5
    done
  else
    log "POKER44_VALIDATOR_ID not set; skipping directory self-match check"
  fi
fi

log "Smoke OK"
