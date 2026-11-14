#!/usr/bin/env bash

# The only command the CI deploy key may run. setup-host.sh installs it as
# /opt/gpx-route-generator/deploy/deploy-gate (root-owned) and pins the key to it with
# `restrict,command=` in authorized_keys. Two actions:
#   upload <sha>    tar.gz of the source (git archive) on stdin -> /opt/gpx-route-generator/releases/<sha>
#   activate <sha>  run the host's root-owned deploy.sh: build with the host's compose file, wait for health
# Nothing from an uploaded release runs on the host itself: it is only the Docker build context.
# The admin key can call it the same way: ssh host /opt/gpx-route-generator/deploy/deploy-gate activate <sha>

set -euo pipefail

ROOT=/opt/gpx-route-generator
read -r -a ARGS <<<"${SSH_ORIGINAL_COMMAND:-$*}"
if [[ "${ARGS[0]:-}" == */deploy-gate ]]; then ARGS=("${ARGS[@]:1}"); fi
ACTION="${ARGS[0]:-}"
RELEASE_ID="${ARGS[1]:-}"

if [[ ${#ARGS[@]} -ne 2 || ! "$RELEASE_ID" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'Usage: deploy-gate upload|activate <40-character commit sha>\n' >&2
    exit 2
fi

case "$ACTION" in
upload)
    dir="$ROOT/releases/$RELEASE_ID"
    rm -rf "$dir"
    mkdir -p "$dir"
    tar -xzf - -C "$dir" --no-same-owner --no-same-permissions
    chmod -R a+rX "$dir"
    printf 'Uploaded %s\n' "$RELEASE_ID"
    ;;
activate)
    exec bash "$ROOT/deploy/deploy.sh" "$RELEASE_ID"
    ;;
*)
    printf 'Unknown action\n' >&2
    exit 2
    ;;
esac
