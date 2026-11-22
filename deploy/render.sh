#!/usr/bin/env bash
# Renders deploy/k8s/imaging.yaml for an environment.
#
#   deploy/render.sh <dev|prod>
#
# Sizing and URLs come from deploy/env/<env>.env; the pipeline exports IMAGE and APP_VERSION.
# Only the listed variables are substituted, and every one of them must be set.
# CORS origin is deliberately absent: it is read from the optional `edge` ConfigMap.
set -euo pipefail

ENVIRONMENT="${1:?usage: deploy/render.sh <dev|prod>}"
DIR="$(cd "$(dirname "$0")" && pwd)"

set -a
# shellcheck disable=SC1090
. "$DIR/env/$ENVIRONMENT.env"
set +a

REQUIRED=(NAMESPACE IMAGE APP_VERSION MIN_REPLICAS MAX_REPLICAS CPU_REQUEST CPU_LIMIT MEMORY_REQUEST MEMORY_LIMIT
          STORAGE_SIZE PUBLIC_BASE_URL VOLVIEW_URL)
for name in "${REQUIRED[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "render.sh: required variable $name is empty" >&2
    exit 1
  fi
done

envsubst "$(printf '${%s} ' "${REQUIRED[@]}")" < "$DIR/k8s/imaging.yaml"
