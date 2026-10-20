# CI scripts

Run by the CI pipeline and usable locally.

```bash
bash scripts/ci/check.sh            # lint, types, tests, frontend build (add --fast to skip Docker and the build)
bash scripts/ci/package-release.sh  # release tarball for the Pi; run after `npm run build` in frontend/
```

```powershell
.\scripts\ci\check.ps1              # same checks in Windows PowerShell (add -Fast to skip Docker and the build)
```

The pipeline is `.github/workflows/ci.yml`: checks on every push and pull request, then a deploy to the Raspberry Pi on pushes to `main`. See `deploy/README.md`.
