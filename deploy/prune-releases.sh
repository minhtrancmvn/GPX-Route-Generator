#!/usr/bin/env bash

# Release retention, run after every successful activation: keep the 5 newest releases, plus every
# release from the last 7 days when there are more than 5, and never the active one. A release's age
# is its folder's modification time, which the deploy gate sets when it unpacks an upload.
# Usage: prune-releases.sh <releases-dir> <active-release-dir>   (prints each removed folder)

set -euo pipefail

RELEASES="${1:?releases dir required}"
ACTIVE="$(readlink -f "${2:?active release required}" || true)"
KEEP_NEWEST=5
KEEP_MINUTES=$((7 * 24 * 60))

count=0
while IFS= read -r dir; do
    dir="${dir%/}"
    count=$((count + 1))
    if ((count <= KEEP_NEWEST)); then continue; fi
    if [[ -n "$(find "$dir" -maxdepth 0 -mmin "-$KEEP_MINUTES")" ]]; then continue; fi
    if [[ -n "$ACTIVE" && "$(readlink -f "$dir")" == "$ACTIVE" ]]; then continue; fi
    rm -rf "$dir"
    printf '%s\n' "$dir"
done < <(ls -1dt "$RELEASES"/*/ 2>/dev/null)
