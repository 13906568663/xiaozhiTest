#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

BRANCH="${1:-dev}"

if [[ ! -f .env.prod ]]; then
  echo "Missing .env.prod. Run: ./scripts/prepare-prod-env.sh"
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
  git checkout "$BRANCH"
fi

# Optional HTTP auth for private Git over HTTP.
# Usage:
#   export GIT_HTTP_USER='auto'
#   export GIT_HTTP_PASSWORD='***'
if [[ -n "${GIT_HTTP_USER:-}" && -n "${GIT_HTTP_PASSWORD:-}" ]]; then
  AUTH="$(printf '%s' "${GIT_HTTP_USER}:${GIT_HTTP_PASSWORD}" | base64 -w0)"
  git -c http.extraHeader="Authorization: Basic $AUTH" fetch origin "$BRANCH"
  git reset --hard "origin/$BRANCH"
else
  git pull --ff-only origin "$BRANCH"
fi

docker compose --env-file .env.prod -f deploy/docker-compose.prod.yml up -d --build

echo "Deployment done."
docker compose --env-file .env.prod -f deploy/docker-compose.prod.yml ps
