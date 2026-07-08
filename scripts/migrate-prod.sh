#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env.prod ]]; then
  echo "Missing .env.prod. Run: ./scripts/prepare-prod-env.sh"
  exit 1
fi

docker compose --env-file .env.prod -f deploy/docker-compose.prod.yml run --rm api alembic upgrade head
