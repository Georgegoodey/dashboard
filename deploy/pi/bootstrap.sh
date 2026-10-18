#!/usr/bin/env bash
# One-time set-up of a Raspberry Pi (64-bit Raspberry Pi OS, Debian bookworm or trixie) to run the Lettings app.
# Safe to run again: it never overwrites an existing /etc/lettings/lettings.env or database role.
#
#   sudo bash deploy/pi/bootstrap.sh /path/to/ci-deploy-key.pub
#
# What it sets up, and why each part is locked down, is explained in deploy/README.md.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "run this as root: sudo bash $0 <deploy-public-key-file>" >&2; exit 1; fi
pubkey_file="${1:-}"
if [[ -z "$pubkey_file" || ! -r "$pubkey_file" ]]; then
  echo "usage: sudo bash $0 /path/to/ci-deploy-key.pub   (the PUBLIC half of the key CI will deploy with)" >&2
  exit 1
fi
pubkey="$(head -n 1 "$pubkey_file")"
[[ "$pubkey" =~ ^(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa)\  ]] || { echo "that does not look like an SSH public key" >&2; exit 1; }

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deploy_dir="$(dirname "$here")"
UV_VERSION=0.13.1   # pinned: the version checked to ship aarch64 wheels
export DEBIAN_FRONTEND=noninteractive

echo "== packages: PostgreSQL, PostGIS, Python tooling =="
apt-get update
apt-get install -y --no-install-recommends postgresql ca-certificates curl gnupg openssl sudo python3 python3-venv
pgver="$(ls /usr/lib/postgresql | sort -n | tail -n 1)"
apt-get install -y --no-install-recommends "postgresql-${pgver}-postgis-3"

echo "== Caddy (official apt repository) =="
if ! command -v caddy >/dev/null; then
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
fi

echo "== uv ${UV_VERSION} (builds the Python environment from the lockfile) =="
if [[ ! -x /opt/lettings/tools/bin/uv ]]; then
  mkdir -p /opt/lettings
  python3 -m venv /opt/lettings/tools
  /opt/lettings/tools/bin/pip install --quiet "uv==${UV_VERSION}"
fi
ln -sfn /opt/lettings/tools/bin/uv /usr/local/bin/uv

echo "== users and folders =="
id lettings >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin lettings
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --groups lettings deploy   # no password set: key login only
usermod -aG lettings,systemd-journal deploy   # journal: so a failed deploy can print the API's log
usermod -aG lettings caddy                    # so Caddy can read the built frontend
mkdir -p /opt/lettings/releases /opt/lettings/bin /etc/lettings
chown deploy:lettings /opt/lettings /opt/lettings/releases
chmod 2750 /opt/lettings /opt/lettings/releases     # group lettings is inherited by every release
chown root:lettings /etc/lettings && chmod 0750 /etc/lettings

echo "== database =="
systemctl enable --now postgresql
env_file=/etc/lettings/lettings.env
if [[ ! -f "$env_file" ]]; then
  app_pw="$(openssl rand -hex 24)"
  ro_pw="$(openssl rand -hex 24)"
  # the app role is NOT a superuser: it owns its database and may create the read-only role (CREATEROLE), nothing more.
  # PostGIS needs a superuser to install, so it is installed here, once, and the app's own migration then finds it.
  # (the passwords go in through stdin, so they never appear in a process list)
  cd /tmp   # the postgres user cannot enter the caller's directory
  runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 <<SQL
\set app_pw '$app_pw'
SELECT format('CREATE ROLE lettings LOGIN CREATEROLE PASSWORD %L', :'app_pw')
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lettings') \gexec
SELECT 'CREATE DATABASE lettings OWNER lettings'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'lettings') \gexec
\connect lettings
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
  install -m 0640 -o root -g lettings "$deploy_dir/pi/lettings.env.example" "$env_file"
  sed -i \
    -e "s#^DATABASE_URL=.*#DATABASE_URL=postgresql://lettings:${app_pw}@127.0.0.1:5432/lettings#" \
    -e "s#^READONLY_DATABASE_URL=.*#READONLY_DATABASE_URL=postgresql://lettings_ro:${ro_pw}@127.0.0.1:5432/lettings#" \
    "$env_file"
  echo "created $env_file with generated database passwords: edit LLM_BASE_URL in it"
else
  echo "$env_file already exists: left as it is (database role and passwords untouched)"
fi
# Debian's default is to listen on localhost only; say so if that has been changed
if ss -ltn 2>/dev/null | grep -E ':5432\s' | grep -vq -E '127\.0\.0\.1:5432|\[::1\]:5432'; then
  echo "WARNING: PostgreSQL is listening beyond localhost. Set listen_addresses = 'localhost' in postgresql.conf." >&2
fi

echo "== service, web server, deploy access =="
install -m 0644 "$deploy_dir/systemd/lettings-api.service" /etc/systemd/system/lettings-api.service
systemctl daemon-reload
systemctl enable lettings-api.service      # starts after the first deploy

install -m 0440 "$deploy_dir/sudoers.d/lettings-deploy" /etc/sudoers.d/lettings-deploy
visudo -cf /etc/sudoers.d/lettings-deploy

# root-owned, so the deploy user (and therefore CI) cannot change what its own key is allowed to run
install -m 0755 -o root -g root "$here/deploy-receive.sh" /opt/lettings/bin/deploy-receive

install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
printf 'restrict,command="/opt/lettings/bin/deploy-receive" %s\n' "$pubkey" >/home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 0600 /home/deploy/.ssh/authorized_keys

install -m 0644 "$deploy_dir/Caddyfile" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl enable caddy
systemctl restart caddy                    # restart (not reload) so the new group membership applies

cat <<'NEXT'

Done. Still to do by hand (needs your Tailscale account), as in deploy/README.md:
  1. edit LLM_BASE_URL in /etc/lettings/lettings.env
  2. curl -fsSL https://tailscale.com/install.sh | sh ; sudo tailscale up
  3. sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
  4. add the GitHub secrets and variable, then merge to main: the first deploy starts the API
NEXT
