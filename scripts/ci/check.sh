#!/usr/bin/env bash
# Everything CI checks, in one script (also usable locally from Git Bash or WSL):
#   scripts/ci/check.sh           lint, types, all tests (integration tests need Docker), front-end types and build
#   scripts/ci/check.sh --fast    lint, types, unit tests only, front-end types (no Docker, no build)
set -euo pipefail

fast=false
[[ "${1:-}" == "--fast" ]] && fast=true
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "== backend: install (locked) =="
cd "$root/backend"
uv sync --frozen

echo "== backend: ruff =="
uv run ruff check .

echo "== backend: mypy =="
uv run mypy

echo "== backend: pytest =="
if $fast; then
  uv run pytest -q -m "not integration"
else
  uv run pytest -q
fi

echo "== frontend: types =="
cd "$root/frontend"
if [[ -n "${CI:-}" ]]; then npm ci; fi
npx tsc -b

if ! $fast; then
  echo "== frontend: build =="
  npm run build
fi

echo "All checks passed."
