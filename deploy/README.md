# Run on a Raspberry Pi

The Pi runs the app; your PC runs Ollama. Everything is reachable only over Tailscale. Merging to `main` deploys automatically.

```
devices ─ tailnet HTTPS ─► tailscale serve ─► Caddy :8080 ─► static files, /api ─► uvicorn :8000 ─► Postgres (all on the Pi)
GitHub Actions ─ joins tailnet as tag:ci ─► SSH forced command ─► deploy-receive (switch, restart, health check, roll back)
```

## Set up (once)

**1. Flash** Raspberry Pi OS Lite, 64-bit, current release (trixie), with SSH enabled. Check on the Pi:

```bash
grep VERSION_CODENAME /etc/os-release   # trixie
uname -m                                # aarch64
```

**2. Make the CI deploy key** on your PC. Keep it in `~/.ssh`, never in the repo.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/lettings-ci-deploy -N "" -C "lettings-ci"
```

Windows PowerShell 5.1 drops an empty `""`, so use `-N '""'` there.

**3. Copy files to the Pi** (public key only), from the repo root. `-i` is your own login key.

```bash
scp -i ~/.ssh/pi-admin -r deploy ~/.ssh/lettings-ci-deploy.pub <user>@<pi-ip>:~/
```

**4. Bootstrap the Pi** (SSH in first: `ssh -i ~/.ssh/pi-admin <user>@<pi-ip>`).

```bash
grep -c $'\r' deploy/pi/bootstrap.sh    # must print 0
sudo DEPLOY_KEY_FROM="100.64.0.0/10" bash deploy/pi/bootstrap.sh ~/lettings-ci-deploy.pub
```

`DEPLOY_KEY_FROM` limits the deploy key to tailnet addresses (optional). Then set the model address:

```bash
sudo nano /etc/lettings/lettings.env    # LLM_BASE_URL=http://<pc-tailscale-ip>:11434
```

**5. Tailscale on the Pi.** Give the Pi a neutral hostname first (HTTPS certificate names are public).

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkgs.tailscale.com/stable/raspbian/trixie.noarmor.gpg | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/raspbian/trixie.tailscale-keyring.list | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt-get update && sudo apt-get install tailscale
sudo tailscale up
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
```

**6. Tailscale admin console.**
- DNS page: turn on MagicDNS and HTTPS certificates.
- Create the tag `tag:ci`; allow it to reach the Pi on port 22 only.
- Allow your own devices to reach the Pi on port 443.
- Create a credential for GitHub to join as `tag:ci` (workload identity federation, or an OAuth client). See Tailscale's GitHub Action page.

**7. GitHub.** Create the `production` environment, then add these. Get the host key from a tailnet device:

```bash
ssh-keyscan -t ed25519 <pi-tailnet-name>
```

| Type | Name | Value |
|---|---|---|
| Secret | `PI_DEPLOY_SSH_KEY` | the **private** key file from step 2 |
| Secret | `PI_KNOWN_HOSTS` | the `ssh-keyscan` output |
| Secret | `TS_OAUTH_CLIENT_ID`, `TS_AUDIENCE` | from step 6 (or the OAuth secret instead) |
| Variable | `PI_HOST` | the Pi's tailnet name |

**8. Ollama on your PC.** Install Tailscale on the PC, then let the Pi reach Ollama (PowerShell):

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "<pc-tailscale-ip>:11434", "User")
```

Restart Ollama fully. Then allow only the Pi through the firewall (run as Administrator):

```powershell
New-NetFirewallRule -DisplayName "Ollama from Pi" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 11434 -RemoteAddress <pi-tailscale-ip> -Profile Any
```

Test from the Pi: `curl http://<pc-tailscale-ip>:11434/api/tags`.

**9. Merge to `main`.** The first deploy starts the API. Check it:

```bash
curl -fsS http://127.0.0.1:8000/health   # "database_ok":true
```

Then open `https://<pi-tailnet-name>` from any device on your tailnet.

## Day to day

```bash
journalctl -u lettings-api -f                                   # app log
sudo ln -sfn /opt/lettings/releases/<old-sha> /opt/lettings/current && sudo systemctl restart lettings-api   # roll back
```

Failed deploys roll back by themselves. Re-run one from the GitHub Actions page.

## Notes

- Migrations run at start and are not undone by a rollback. Keep each one compatible with the previous code.
- Use trixie (PostgreSQL 17). On bookworm the app's database role is more powerful; bootstrap warns.
- Not yet run on a real Pi. Still to do: restrict SSH to `tailscale0`, and back up the database (`pg_dump`).
- Files here: `Caddyfile`, `systemd/lettings-api.service`, `sudoers.d/lettings-deploy`, `pi/bootstrap.sh`, `pi/deploy-receive.sh`, `pi/lettings.env.example`.
