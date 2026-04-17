#!/usr/bin/env bash
# Pull the Isaac Sim image declared in docker/docker-compose.yml.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/docker"

echo "[build] Pulling Isaac Sim image (first run: ~20GB, may take 10+ min)"
docker compose pull

echo "[build] Done. Run ./run.sh to start the container."
