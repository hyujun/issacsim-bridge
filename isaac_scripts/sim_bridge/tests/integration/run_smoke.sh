#!/usr/bin/env bash
# Host-side helper: run launch_sim.py inside the isaac-sim container with env
# overrides, capture logs to a file, and exit with the container exit code.
#
# Used by Phase 1.2 per-patch validation and any future headless smoke test.
# Does NOT require the persistent `isaac-sim` service to be up — uses
# `docker compose run --rm` which creates an ephemeral container.
#
# Usage:
#   SIM_HEADLESS=1 SIM_SKIP_PATCHES=repair_joint_chain SIM_MAX_RUN_SECONDS=45 \
#     tests/integration/run_smoke.sh <log_file>
#
# Env forwarded to the container:
#   ROBOT (default ur5e)       — picks robots/<name>/
#   SIM_HEADLESS               — 1 to disable GUI
#   SIM_SKIP_PATCHES           — comma-separated USD-patch names to skip
#   SIM_MAX_RUN_SECONDS        — auto-close after N seconds of sim loop

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
LOG_FILE="${1:-/tmp/isaac_smoke.log}"

: "${ROBOT:=ur5e}"
: "${ROBOT_PACK:=/workspace/robots/${ROBOT}}"
: "${SIM_HEADLESS:=1}"
: "${SIM_SKIP_PATCHES:=}"
: "${SIM_MAX_RUN_SECONDS:=45}"

cd "${REPO_DIR}/docker"

# Ensure any leftover persistent container is down so `run` doesn't conflict
# with the named service. `down` is idempotent.
docker compose down >/dev/null 2>&1 || true

echo "[smoke] ROBOT=${ROBOT}  SIM_HEADLESS=${SIM_HEADLESS}  SIM_SKIP_PATCHES='${SIM_SKIP_PATCHES}'  SIM_MAX_RUN_SECONDS=${SIM_MAX_RUN_SECONDS}"
echo "[smoke] log -> ${LOG_FILE}"

set +e
docker compose run --rm \
    -e ROBOT_PACK="${ROBOT_PACK}" \
    -e SIM_HEADLESS="${SIM_HEADLESS}" \
    -e SIM_SKIP_PATCHES="${SIM_SKIP_PATCHES}" \
    -e SIM_MAX_RUN_SECONDS="${SIM_MAX_RUN_SECONDS}" \
    isaac-sim /workspace/scripts/launch_sim.py 2>&1 | tee "${LOG_FILE}"
rc=${PIPESTATUS[0]}
set -e

echo "[smoke] container exit code: ${rc}"
exit "${rc}"
