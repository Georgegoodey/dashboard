#!/usr/bin/env bash
# Builds the release tarball the Pi installs: backend/ (code, migrations and the lockfile; no tests, caches or virtualenv)
# and web/ (the built frontend). Run it after `npm run build`; the deploy job in .github/workflows/ci.yml does.
#   bash scripts/ci/package-release.sh [output.tgz]      (default: release.tgz in the repository root)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="${1:-$root/release.tgz}"

if [[ ! -f "$root/frontend/dist/index.html" ]]; then
  echo "frontend/dist is missing: build the frontend first (cd frontend && npm run build)" >&2
  exit 1
fi

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/backend" "$stage/web"

cp -r "$root/backend/app" "$root/backend/migrations" "$stage/backend/"
cp "$root/backend/pyproject.toml" "$root/backend/uv.lock" "$root/backend/alembic.ini" "$stage/backend/"
find "$stage/backend" -name __pycache__ -type d -prune -exec rm -rf {} +
cp -r "$root/frontend/dist/." "$stage/web/"

tar --force-local -czf "$out" -C "$stage" backend web
echo "wrote $out ($(du -h "$out" | cut -f1))"
