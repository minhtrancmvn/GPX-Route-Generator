#!/usr/bin/env bash
# Idempotent host setup for production deploys: /opt/gpx-route-generator with the root-owned deploy
# gate, activation script (deploy.sh) and compose file, the production .env, and the GPX nginx vhost.
# Run on the server as the admin user (sudo + docker group), from a copied deploy/ dir:
#   bash setup-host.sh
#   CI_PUBLIC_KEY="ssh-ed25519 AAAA... gpx-route-generator GitHub Actions deploy" bash setup-host.sh
# With CI_PUBLIC_KEY, the CI key's line in authorized_keys is replaced by one pinned to the gate:
# that key can then only upload and activate releases, nothing else.
# Re-run after changing deploy-gate.sh, deploy.sh, compose.production.yml or nginx-gpx.conf: the
# host only ever uses its own copies of them.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT=/opt/gpx-route-generator
ADMIN="$(id -un)"
# The layout before the move to /opt: its .env and live release are copied over once.
OLD_ROOT="$HOME/gpx-route-generator"
DOMAIN=gpx-route-generator.minhtran.id.vn

fail() { printf '%s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -ne 0 ]] || fail 'Run as the admin user (with sudo), not root.'
docker compose version >/dev/null 2>&1 || fail 'Install Docker Engine and the Compose v2 plugin first.'
id -nG | grep -qw docker || fail "$ADMIN must be in the docker group: the gate runs docker compose as this user."

# The admin user owns releases, `current` and .env (the gate runs as it); the scripts and the compose
# file are root-owned so neither the CI key nor an uploaded release can change them.
sudo install -d -o "$ADMIN" -g "$ADMIN" -m 755 "$ROOT" "$ROOT/releases"
sudo install -d -o root -g root -m 755 "$ROOT/deploy"
sudo install -o root -g root -m 755 "$DEPLOY_DIR/deploy-gate.sh" "$ROOT/deploy/deploy-gate"
sudo install -o root -g root -m 755 "$DEPLOY_DIR/deploy.sh" "$ROOT/deploy/deploy.sh"
sudo install -o root -g root -m 755 "$DEPLOY_DIR/prune-releases.sh" "$ROOT/deploy/prune-releases.sh"
sudo install -o root -g root -m 644 "$DEPLOY_DIR/compose.production.yml" "$ROOT/deploy/compose.production.yml"

if [[ ! -f "$ROOT/.env" && -f "$OLD_ROOT/.env" ]]; then
    install -m 600 "$OLD_ROOT/.env" "$ROOT/.env"
    printf 'Copied %s/.env\n' "$OLD_ROOT"
fi
[[ -f "$ROOT/.env" ]] || fail "Create $ROOT/.env (mode 600) from .env.example, then re-run."
chmod 600 "$ROOT/.env"

if [[ ! -e "$ROOT/current" && -L "$OLD_ROOT/current" ]]; then
    live="$(readlink -f "$OLD_ROOT/current")"
    release_id="$(basename "$live")"
    cp -a "$live" "$ROOT/releases/$release_id"
    # Old releases carried a .env symlink; the host's compose file reads $ROOT/.env directly.
    if [[ -L "$ROOT/releases/$release_id/.env" ]]; then rm -f "$ROOT/releases/$release_id/.env"; fi
    chmod -R a+rX "$ROOT/releases/$release_id"
    ln -sfn "$ROOT/releases/$release_id" "$ROOT/current"
    printf 'Copied live release %s to %s/releases\n' "$release_id" "$ROOT"
fi

# The vhost used to be installed by every deploy; now only from here.
target="/etc/nginx/sites-available/$DOMAIN"
link="/etc/nginx/sites-enabled/$DOMAIN"
if ! sudo cmp -s "$DEPLOY_DIR/nginx-gpx.conf" "$target"; then
    backup=''
    if sudo test -e "$target"; then
        backup="$target.bak-$(date +%Y%m%d%H%M%S)"
        sudo cp -p "$target" "$backup"
    fi
    sudo install -m 644 "$DEPLOY_DIR/nginx-gpx.conf" "$target"
    sudo ln -sfn "$target" "$link"
    if ! sudo nginx -t; then
        if [[ -n "$backup" ]]; then sudo cp -p "$backup" "$target"; else sudo rm -f "$target" "$link"; fi
        fail 'nginx rejected nginx-gpx.conf; the previous vhost was restored.'
    fi
    sudo systemctl reload nginx
    printf 'Installed the %s vhost\n' "$DOMAIN"
fi

if [[ -n "${CI_PUBLIC_KEY:-}" ]]; then
    blob="$(awk '{print $2}' <<<"$CI_PUBLIC_KEY")"
    [[ "$blob" =~ ^AAAA[0-9A-Za-z+/=]{20,}$ ]] || fail 'CI_PUBLIC_KEY does not look like a public key line.'
    keys="$HOME/.ssh/authorized_keys"
    cp -p "$keys" "$keys.bak-$(date +%Y%m%d%H%M%S)"
    { grep -vF " $blob" "$keys" || true; printf 'restrict,command="%s/deploy/deploy-gate" %s\n' "$ROOT" "$CI_PUBLIC_KEY"; } >"$keys.new"
    chmod 600 "$keys.new"
    mv "$keys.new" "$keys"
    printf 'CI key pinned to %s/deploy/deploy-gate\n' "$ROOT"
fi

printf 'Host ready. The next deploy (or: %s/deploy/deploy-gate activate <sha>) runs from %s.\n' "$ROOT" "$ROOT"
