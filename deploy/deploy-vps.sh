#!/usr/bin/env bash
# Deploy the exact main branch revision to a single Docker VPS.
# This script intentionally preserves the server-local .env, instance/, and logs/.
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/truck-management}"
BRANCH="${DEPLOY_BRANCH:-main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5000/health}"
MAX_HEALTH_ATTEMPTS="${MAX_HEALTH_ATTEMPTS:-30}"

cd "$APP_DIR"

echo "Deploying origin/$BRANCH to $APP_DIR"
git fetch --prune origin "$BRANCH"
git checkout --detach "origin/$BRANCH"

# The first server setup creates these directories and assigns them to UID/GID
# 10001, the non-root account used inside the application container.
mkdir -p instance/uploads logs

docker compose up -d --build --remove-orphans

for attempt in $(seq 1 "$MAX_HEALTH_ATTEMPTS"); do
    if curl --fail --silent --show-error "$HEALTH_URL"; then
        echo
        echo "Deployment is healthy."
        docker compose ps
        docker image prune --force
        exit 0
    fi

    echo "Waiting for health check ($attempt/$MAX_HEALTH_ATTEMPTS)..."
    sleep 2
done

echo "Deployment failed: $HEALTH_URL did not become healthy." >&2
docker compose ps >&2 || true
docker compose logs --tail=100 web >&2 || true
exit 1
