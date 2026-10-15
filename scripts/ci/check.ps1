# The same checks as check.sh, for Windows PowerShell, using the project's own backend\.venv.
#   .\scripts\ci\check.ps1           lint, types, all tests (integration tests need Docker), front-end types and build
#   .\scripts\ci\check.ps1 -Fast     lint, types, unit tests only, front-end types (no Docker, no build)
param([switch]$Fast)
$ErrorActionPreference = "Continue"   # native tools write warnings to stderr; failures are caught through exit codes below
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$venv = "$root\backend\.venv\Scripts"

function Step($name, [scriptblock]$cmd) {
    Write-Host "== $name =="
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$name failed" }
}

Push-Location "$root\backend"
try {
    Step "backend: ruff" { & "$venv\ruff.exe" check . }
    Step "backend: mypy" { & "$venv\mypy.exe" }
    if ($Fast) { Step "backend: pytest (unit)" { & "$venv\python.exe" -m pytest -q -m "not integration" } }
    else { Step "backend: pytest" { & "$venv\python.exe" -m pytest -q } }
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    Step "frontend: types" { npx tsc -b }
    if (-not $Fast) { Step "frontend: build" { npm run build } }
} finally { Pop-Location }

Write-Host "All checks passed."
