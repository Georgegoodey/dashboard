#!/usr/bin/env bash
# Installed by bootstrap.sh as /opt/lettings/bin/deploy-receive, owned by root so the deploy user cannot change it.
# It is the SSH "forced command" of the CI deploy key: the key can run this and nothing else.
#
#   stdin:                a release tarball (backend/ and web/) made by scripts/ci/package-release.sh
#   SSH_ORIGINAL_COMMAND: the 40-character commit sha of that release
#
# It unpacks the release, builds its Python environment from the lockfile, switches `current`, restarts the API and waits
# for /health to report a working database. If that fails it switches back to the previous release.
# Database migrations run when the API starts (see deploy/README.md: they must stay backward compatible).
set -euo pipefail
umask 027

ROOT=/opt/lettings
KEEP=3
HEALTH_URL=http://127.0.0.1:8000/health
WAIT_SECONDS=90

sha="${SSH_ORIGINAL_COMMAND:-${1:-}}"
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "refusing: the release id must be a 40-character commit sha" >&2
  exit 2
fi
release="$ROOT/releases/$sha"

restart_api() { sudo -n /usr/bin/systemctl restart lettings-api.service; }

# true once /health says the API is up and its database is connected and migrated
healthy() {
  local deadline=$((SECONDS + WAIT_SECONDS))
  while ((SECONDS < deadline)); do
    if curl -fsS --max-time 3 "$HEALTH_URL" 2>/dev/null \
      | python3 -c 'import json, sys; d = json.load(sys.stdin); sys.exit(0 if d.get("status") == "ok" and d.get("database_ok") is True else 1)' 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

switch_to() {
  ln -sfn "$1" "$ROOT/current.next"
  mv -T "$ROOT/current.next" "$ROOT/current"
}

previous="$(readlink -f "$ROOT/current" 2>/dev/null || true)"

if [[ "$previous" == "$release" ]]; then
  echo "release $sha is already live: restarting and checking health"
  restart_api
  healthy && echo "healthy" && exit 0
  journalctl -u lettings-api.service -n 40 --no-pager || true
  exit 1
fi

installed=false
cleanup() { $installed || rm -rf "$release"; }
trap cleanup EXIT

rm -rf "$release"
mkdir -p "$release"
echo "unpacking release $sha"
# GNU tar refuses absolute paths and ".." members by default
tar -xzf - -C "$release" --no-same-owner --no-same-permissions

for f in backend/pyproject.toml backend/uv.lock backend/alembic.ini web/index.html; do
  [[ -f "$release/$f" ]] || { echo "refusing: the release is missing $f" >&2; exit 2; }
done

echo "building the Python environment from uv.lock"
(cd "$release/backend" && UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy uv sync --frozen --no-dev)

switch_to "$release"
installed=true
echo "restarting the API"
restart_api

if healthy; then
  echo "release $sha is live"
  # keep the newest few releases (never the live one) so a rollback is always possible
  find "$ROOT/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | tail -n +$((KEEP + 1)) | cut -d' ' -f2- \
    | while read -r old; do [[ "$(readlink -f "$old")" == "$(readlink -f "$ROOT/current")" ]] || rm -rf "$old"; done
  exit 0
fi

echo "release $sha failed its health check" >&2
journalctl -u lettings-api.service -n 40 --no-pager || true
if [[ -n "$previous" && -d "$previous" ]]; then
  echo "rolling back to $(basename "$previous")" >&2
  switch_to "$previous"
  restart_api
  if healthy; then echo "rolled back and healthy" >&2; else echo "ROLLBACK ALSO UNHEALTHY: check the Pi" >&2; fi
else
  echo "no previous release to roll back to" >&2
fi
exit 1
