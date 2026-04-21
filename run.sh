#!/usr/bin/env bash
# Launch Isaac Sim with Newton + ROS 2 bridge via docker compose.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/docker"

if ! xhost | grep -q "LOCAL:"; then
  echo "[run] granting X11 access to local docker"
  xhost +local:docker >/dev/null
fi

: "${ROS_DOMAIN_ID:=0}"
export ROS_DOMAIN_ID

: "${RMW_IMPLEMENTATION:=rmw_cyclonedds_cpp}"
export RMW_IMPLEMENTATION

# Robot pack selector — picks which robots/<name>/ directory the sim loads.
# Override: ROBOT=hand ./run.sh, or set ROBOT_PACK directly to a container path.
: "${ROBOT:=ur5e}"
: "${ROBOT_PACK:=/workspace/robots/${ROBOT}}"
export ROBOT_PACK

MODE="${1:-up}"
case "${MODE}" in
  up)      docker compose up ;;
  upd)     docker compose up -d ;;
  down)    docker compose down ;;
  logs)    docker compose logs -f ;;
  shell)   docker compose exec isaac-sim bash ;;
  restart) docker compose down && docker compose up ;;
  convert) docker compose run --rm --no-deps isaac-sim "${ROBOT_PACK}/convert_urdf.py" ;;
  list)
    # Enumerate available packs — name · DOF · sim.mode. Reads robot.yaml on host
    # via python3+yaml (no docker round-trip). If python3-yaml is missing, fall
    # back to name-only listing.
    printf '%-22s %s\n' "PACK" "CONTENTS"
    for yaml in "${SCRIPT_DIR}"/robots/*/robot.yaml; do
      [ -f "${yaml}" ] || continue
      name="$(basename "$(dirname "${yaml}")")"
      details="$(python3 -c '
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
n = len(c.get("joint_names") or [])
m = (c.get("sim") or {}).get("mode", "freerun")
r = (c.get("robot") or {}).get("root_link", "?")
print(f"{n} DoF, sim.mode={m}, root_link={r}")
' "${yaml}" 2>/dev/null)" || details=""
      printf '%-22s %s\n' "${name}" "${details:-(parse failed)}"
    done
    ;;
  *)
    echo "usage: $0 [up|upd|down|logs|shell|restart|convert|list]" >&2
    echo "  ROBOT=<name> selects robots/<name>/ (default: ur5e)" >&2
    echo "  list         enumerate available robot packs" >&2
    exit 1
    ;;
esac
