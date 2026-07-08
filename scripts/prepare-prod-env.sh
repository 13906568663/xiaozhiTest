#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env.prod ]]; then
  echo ".env.prod already exists, skip."
  exit 0
fi

cp .env.prod.example .env.prod
chmod 600 .env.prod

echo "Created .env.prod from .env.prod.example"
echo "Please edit .env.prod before first deployment."
