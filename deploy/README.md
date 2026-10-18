# Running the app on a Raspberry Pi

The Pi runs everything except the language model. Your PC runs Ollama, and the Pi reaches it over Tailscale. Every merge
to `main` that passes CI deploys itself.

```
phone / laptop ── tailnet (HTTPS) ──► tailscale serve ──► Caddy 127.0.0.1:8080 ──► static files
                                                                │
                                                                └─ /api, /health ──► uvicorn 127.0.0.1:8000 (one worker) ──► Postgres (local)
                                                                                           │
                                                                          Ollama on your PC, over the tailnet
GitHub Actions (merge to main) ── joins the tailnet as tag:ci ──► SSH, forced command ──► deploy-receive (switch release, restart, health check, roll back)
```

Nothing on the Pi listens on your LAN or the internet for the app. Caddy and uvicorn bind to `127.0.0.1`; Postgres listens on
localhost; only `tailscale serve` (and SSH, see below) are reachable, and only from your own devices.

## What is where

| File | Purpose |
|---|---|
| `Caddyfile` | static frontend, `/api` and `/health` proxy, cache and security headers. No TLS or login: the tailnet is the access control. |
| `systemd/lettings-api.service` | the API as a sandboxed service, **one worker** (the job scheduler runs inside it and cannot be shared between processes) |
| `sudoers.d/lettings-deploy` | lets the deploy user restart that one service as root, nothing else |
| `pi/bootstrap.sh` | one-time set-up of a fresh Pi (run by hand) |
| `pi/deploy-receive.sh` | what CI runs on every deploy (installed root-owned by bootstrap) |
| `pi/lettings.env.example` | the API's settings on the Pi |
| `../scripts/ci/package-release.sh` | builds the tarball CI sends |
| `../.github/workflows/ci.yml` | the `deploy` job |

## One-time set-up

1. **Flash the Pi** with 64-bit Raspberry Pi OS Lite (current release is Debian trixie; bookworm works too), enable SSH, boot it.
   Prefer an SSD over an SD card for the database.
2. **Make a deploy key** on your PC (a key used only by CI):
   `ssh-keygen -t ed25519 -f lettings-ci-deploy -N "" -C "lettings-ci"`
3. **Bootstrap the Pi.** Copy the `deploy/` folder and the public key to it, then:
   `sudo bash deploy/pi/bootstrap.sh lettings-ci-deploy.pub`
   It installs PostgreSQL and PostGIS from Debian (the official `postgis/postgis` Docker images have no arm64 build), Caddy, and
   `uv`; creates the `lettings` (service) and `deploy` (CI) users; creates the database with a non-superuser app role; and
   installs the service, the Caddyfile and the deploy receiver. It prints what is left to do.
4. **Edit `/etc/lettings/lettings.env`** on the Pi: set `LLM_BASE_URL` to your PC (below). The database passwords are already
   generated.
5. **Join Tailscale on the Pi**, then publish Caddy to your tailnet over HTTPS:
   ```
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
   ```
   HTTPS certificates need MagicDNS and HTTPS enabled on the Tailscale admin DNS page. That publishes the machine's name in
   public Certificate Transparency logs, so give the Pi a neutral name first.
6. **Tailscale admin console:** create the tag `tag:ci`; allow `tag:ci` to reach the Pi on port 22 and nothing else; allow your own
   devices to reach the Pi on 443. Then let GitHub join as `tag:ci` using either a workload identity federation credential
   (recommended, no stored secret) or an OAuth client. See Tailscale's *GitHub Action* page for the exact steps.
7. **GitHub:** create the `production` environment (add required reviewers if you want a manual gate) and add
   - secrets: `PI_DEPLOY_SSH_KEY` (the **private** key from step 2), `PI_KNOWN_HOSTS` (the Pi's host key, from
     `ssh-keyscan -t ed25519 <pi-tailnet-name>` run over the tailnet), `TS_OAUTH_CLIENT_ID` and `TS_AUDIENCE`
     (or the OAuth secret if you use that instead);
   - variable: `PI_HOST` (the Pi's tailnet name).
8. **Merge to `main`.** The first deploy installs the app and starts the API.

## The model on your PC

Ollama listens on `127.0.0.1` by default, so the Pi cannot reach it. Put the PC on the tailnet, then either
- set the user environment variable `OLLAMA_HOST` to the PC's Tailscale address and port `11434` (so it is not exposed on your
  LAN), restart Ollama, and add a Windows firewall rule that allows port 11434 only from the Pi's Tailscale address; or
- leave Ollama on `127.0.0.1` and run `tailscale serve` on the PC to publish it to the tailnet only.

Ollama has no login of its own, so never expose it beyond the tailnet. If the PC is off, only chat stops working: `/health`
reports the model as unreachable and the rest of the app carries on.

## Database migrations

Migrations run when the API starts. A deploy that fails its health check is rolled back to the previous code, but a migration
that already ran stays applied. Keep every migration compatible with the code before it (add columns and tables; remove or
rename them in a later release).

## Day to day

- Logs: `journalctl -u lettings-api -f` (and `journalctl -u caddy`).
- Releases live in `/opt/lettings/releases/<sha>`, `/opt/lettings/current` points at the live one, and the newest three are kept.
- Manual rollback: `sudo ln -sfn /opt/lettings/releases/<old-sha> /opt/lettings/current && sudo systemctl restart lettings-api`.
- Re-run a failed deploy from the GitHub Actions page; deploying the live sha just restarts it and checks health.

## Hardening you may still want

- SSH is open on the Pi's LAN address as well as the tailnet. Restrict it to the tailnet (for example a firewall rule that allows
  port 22 only on `tailscale0`), after confirming you can still reach the Pi over Tailscale.
- Add a Content-Security-Policy to the Caddyfile once tested against the map (it loads tiles and a worker from other origins).
- Back up the database (`pg_dump` on a timer, copied off the Pi).

## What has and has not been tested

Tested on the development PC:
- the production switches in the API (docs off, `/health` hides the model address) and the full CI script, including the
  Docker integration tests and the frontend build;
- the database set-up: the app migrates and provisions its read-only role as a **non-superuser** (`CREATEROLE` only, PostGIS
  installed beforehand), on PostgreSQL 15, 16 and 17 (`backend/tests/test_least_privilege_database.py`);
- the Caddyfile: it validates with Caddy 2.11, and behind a real Caddy container the page, cache and security headers (also on
  error pages), gzip, the `/api` and `/health` proxy, and blocked `/docs` and `/openapi.json` all behave as described;
- the chat stream passes through Caddy chunk by chunk, not held back until the end;
- `deploy-receive.sh` in a Debian container with `systemctl` stubbed: first deploy, a second deploy, redeploying the live
  release, a broken release rolling back, refusal of a bad id or incomplete tarball, file ownership, and what the deploy user can
  run through `sudo` (24 checks);
- the database step of `bootstrap.sh` (the `psql` block), run twice on a throwaway PostGIS server: it creates the non-superuser
  role, the database and the extensions, and is safe to repeat;
- that every locked Python dependency has an aarch64 wheel for Python 3.11 and 3.13, that the release tarball contains what the
  receiver requires, that the workflow file parses, and the shell scripts' syntax.

Not tested, because it needs a real Pi, your Tailscale account or GitHub: the rest of `bootstrap.sh` (apt packages, user and folder creation), the systemd unit and its sandbox settings, `tailscale serve`, the SSH forced command and key, the Tailscale
GitHub Action, and the first real deploy. Expect to fix small things on the first run.
