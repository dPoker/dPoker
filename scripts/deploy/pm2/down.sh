#!/usr/bin/env bash
set -euo pipefail

# Stop all PM2 apps created by scripts/deploy/pm2/up.sh.
#
# Usage:
#   cd poker44-subnet
#   bash scripts/deploy/pm2/down.sh

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$here/../../.." && pwd)"
platform_backend_dir="${PLATFORM_BACKEND_DIR:-$repo_dir/../platform/backend}"

die() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

command -v pm2 >/dev/null 2>&1 || die "pm2 not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found"

pm2_prefix="${PM2_PREFIX:-poker44-p2p}"
stop_docker="${STOP_DOCKER:-false}"

log "Stopping PM2 apps with prefix: $pm2_prefix"
names="$(pm2 jlist | python3 - <<PY
import json, sys
prefix = "$pm2_prefix" + "-"
apps = json.load(sys.stdin) if not sys.stdin.isatty() else []
out=[]
for a in apps:
  name = (a.get("name") or "")
  if isinstance(name, str) and name.startswith(prefix):
    out.append(name)
print("\\n".join(sorted(set(out))))
PY
)"

if [ -n "$names" ]; then
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    log "pm2 delete $name"
    pm2 delete "$name" >/dev/null 2>&1 || true
  done <<<"$names"
else
  log "No matching PM2 apps found."
fi

pm2 save >/dev/null 2>&1 || true

deploy_env_file="$repo_dir/.p2p_deploy.env"
remove_deploy_env="${REMOVE_DEPLOY_ENV:-auto}"
if [ -f "$deploy_env_file" ]; then
  file_prefix="$(python3 - <<'PY' <"$deploy_env_file"
import sys
p = ""
for line in sys.stdin.read().splitlines():
  if line.startswith("PM2_PREFIX="):
    p = line.split("=", 1)[1].strip()
    break
print(p)
PY
)"

  should_remove="false"
  case "${remove_deploy_env,,}" in
    true)
      should_remove="true"
      ;;
    false)
      should_remove="false"
      ;;
    *)
      # auto
      if [ -n "$file_prefix" ]; then
        if [ "$file_prefix" = "$pm2_prefix" ]; then
          should_remove="true"
        fi
      else
        # Back-compat: old files had no prefix; only remove for the default stack.
        if [ "$pm2_prefix" = "poker44-p2p" ]; then
          should_remove="true"
        fi
      fi
      ;;
  esac

  if [ "$should_remove" = "true" ]; then
    rm -f "$deploy_env_file"
  fi
fi

if [ "${stop_docker,,}" = "true" ]; then
  log "Stopping platform docker compose (STOP_DOCKER=true)"
  if [ -d "$platform_backend_dir" ]; then
    ( cd "$platform_backend_dir" && npm run docker:down ) || true
  fi
fi

log "Down."
