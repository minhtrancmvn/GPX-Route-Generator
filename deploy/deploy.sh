#!/usr/bin/env bash
# On the host, run by deploy-gate. Both are root-owned copies in /opt/gpx-route-generator/deploy
# (installed by setup-host.sh), as is the compose file: the uploaded release is only the build
# context, so nothing in it decides how the container runs. Builds before replacing the app, waits
# for health, restores the previous release on failure, then points `current` at the new one.
# Usage: deploy.sh COMMIT_SHA
set -euo pipefail

sha=${1:?Usage: deploy.sh COMMIT_SHA}
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || { printf 'Invalid commit SHA\n' >&2; exit 1; }

root=/opt/gpx-route-generator
release="$root/releases/$sha"
env_file="$root/.env"
compose_file="$root/deploy/compose.production.yml"
[[ -f "$env_file" ]] || { printf 'Production env file missing\n' >&2; exit 1; }
[[ "$(stat -c '%a' "$env_file")" == 600 ]] || { printf 'Production .env must have mode 600\n' >&2; exit 1; }
[[ -f "$release/Dockerfile" ]] || { printf 'Release missing\n' >&2; exit 1; }

exec 9>"$root/deploy.lock"
flock -n 9 || { printf 'Another deployment is running\n' >&2; exit 1; }
previous=$(readlink -f "$root/current" || true)
if [[ "$previous" == "$release" ]]; then
    previous=''
fi

export DEPLOY_ROOT="$root" DEPLOY_SHA="$sha" GPX_RELEASE="$release"
compose=(docker compose --project-name gpx-route-generator --env-file "$env_file" -f "$compose_file")
rollback_app() {
    printf 'Deployment activation failed; restoring previous release if available\n' >&2
    if [[ "$previous" == "$root/releases/"* && -d "$previous" ]]; then
        DEPLOY_SHA="${previous##*/}" GPX_RELEASE="$previous" \
            "${compose[@]}" up --detach --no-build --wait --wait-timeout 120
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

ln -sfn "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
printf 'Deployed %s\n' "$sha"
