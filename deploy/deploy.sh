#!/usr/bin/env bash
set -euo pipefail

root=${1:?Usage: deploy.sh DEPLOY_ROOT COMMIT_SHA}
sha=${2:?Usage: deploy.sh DEPLOY_ROOT COMMIT_SHA}
[[ "$root" =~ ^/home/[a-zA-Z0-9_-]+/[a-zA-Z0-9/_-]+$ ]] || { printf 'Invalid deployment root\n' >&2; exit 1; }
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || { printf 'Invalid commit SHA\n' >&2; exit 1; }

release="$root/releases/$sha"
export DEPLOY_ROOT="$root"
export GPX_ENV_FILE="$root/.env"
[[ -f "$GPX_ENV_FILE" ]] || { printf 'Production env file missing\n' >&2; exit 1; }
[[ "$(stat -c '%a' "$GPX_ENV_FILE")" == 600 ]] || { printf 'Production .env must have mode 600\n' >&2; exit 1; }
[[ -f "$release/deploy/compose.production.yml" ]] || { printf 'Release missing\n' >&2; exit 1; }

# Keep runtime config beside the release pointer, matching Task Automation layout.
ln -sfn "$GPX_ENV_FILE" "$release/.env"

exec 9>"$root/deploy.lock"
flock -n 9 || { printf 'Another deployment is running\n' >&2; exit 1; }
previous=$(readlink -f "$root/current" || true)
if [[ "$previous" == "$release" ]]; then
    previous=''
fi

export DEPLOY_SHA="$sha"
compose=(docker compose --project-name gpx-route-generator --env-file "$GPX_ENV_FILE" -f "$release/deploy/compose.production.yml")
rollback_app() {
    printf 'Deployment activation failed; restoring previous release if available\n' >&2
    if [[ "$previous" == "$root/releases/"* && -f "$previous/deploy/compose.production.yml" ]]; then
        export DEPLOY_SHA="${previous##*/}"
        docker compose --project-name gpx-route-generator --env-file "$GPX_ENV_FILE" \
            -f "$previous/deploy/compose.production.yml" up --detach --no-build --wait --wait-timeout 120
        ln -sfn "$previous" "$root/current.next"
        mv -Tf "$root/current.next" "$root/current"
    else
        "${compose[@]}" down
    fi
}

"${compose[@]}" config --quiet
"${compose[@]}" build --pull
if ! "${compose[@]}" up --detach --remove-orphans --wait --wait-timeout 120; then
    rollback_app
    exit 1
fi

nginx_target=/etc/nginx/sites-available/gpx-route-generator.minhtran.id.vn
nginx_link=/etc/nginx/sites-enabled/gpx-route-generator.minhtran.id.vn
nginx_backup="$root/nginx-gpx.previous"
nginx_existed=false
if sudo test -e "$nginx_target"; then
    sudo cp -p "$nginx_target" "$nginx_backup"
    nginx_existed=true
fi
nginx_previous=$(readlink -f "$nginx_link" || true)
restore_nginx() {
    if [[ "$nginx_existed" == true ]]; then
        sudo cp -p "$nginx_backup" "$nginx_target"
    else
        sudo rm -f "$nginx_target"
    fi
    if [[ -n "$nginx_previous" ]]; then
        sudo ln -sfn "$nginx_previous" "$nginx_link.next"
        sudo mv -Tf "$nginx_link.next" "$nginx_link"
    else
        sudo rm -f "$nginx_link"
    fi
    sudo nginx -t && sudo systemctl reload nginx
}

sudo install -m 644 "$release/deploy/nginx-gpx.conf" "$nginx_target.next"
sudo mv -f "$nginx_target.next" "$nginx_target"
sudo ln -sfn "$nginx_target" "$nginx_link.next"
sudo mv -Tf "$nginx_link.next" "$nginx_link"
if ! sudo nginx -t; then
    restore_nginx
    rollback_app
    exit 1
fi
if ! sudo systemctl reload nginx; then
    restore_nginx
    rollback_app
    exit 1
fi

ln -sfn "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
printf 'Deployed %s\n' "$sha"
