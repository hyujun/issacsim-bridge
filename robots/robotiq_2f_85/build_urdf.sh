#!/usr/bin/env bash
# Regenerate urdf/robotiq_2f_85.urdf from ros-jazzy-robotiq-description xacro.
#
# Run on the HOST (uses /opt/ros/jazzy). After ./install.sh has installed
# ros-jazzy-xacro + ros-jazzy-robotiq-description. The generated URDF is
# committed to the pack — the container never re-runs xacro.
set -euo pipefail

PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XACRO_SRC=/opt/ros/jazzy/share/robotiq_description/urdf/robotiq_2f_85_gripper.urdf.xacro
URDF_OUT="${PACK_DIR}/urdf/robotiq_2f_85.urdf"
MESHES_SRC=/opt/ros/jazzy/share/robotiq_description/meshes
MESHES_DST="${PACK_DIR}/urdf/meshes"

if [ ! -d /opt/ros/jazzy ]; then
  echo "error: ROS 2 Jazzy not installed at /opt/ros/jazzy" >&2
  exit 1
fi
if [ ! -f "${XACRO_SRC}" ]; then
  echo "error: ros-jazzy-robotiq-description not installed (missing ${XACRO_SRC})" >&2
  echo "       run ./install.sh first" >&2
  exit 1
fi

source /opt/ros/jazzy/setup.bash

mkdir -p "${MESHES_DST}/visual" "${MESHES_DST}/collision"
cp -u "${MESHES_SRC}"/visual/*.{dae,stl} "${MESHES_DST}/visual/" 2>/dev/null || true
cp -u "${MESHES_SRC}"/collision/*.{dae,stl} "${MESHES_DST}/collision/" 2>/dev/null || true

xacro "${XACRO_SRC}" -o "${URDF_OUT}"

# Rewrite absolute file:// mesh paths to pack-relative so the URDF is
# self-contained (the sim runs from a container where /opt/ros paths differ).
python3 - "${URDF_OUT}" <<'PY'
import re, sys
path = sys.argv[1]
s = open(path).read()
# file:///.../robotiq_description/meshes/  ->  meshes/
s = re.sub(r'file://[^"]*?/robotiq_description/meshes/', 'meshes/', s)
# Strip ros2_control block (ros2_control hardware abstraction; unused here).
s = re.sub(r'\s*<ros2_control\b.*?</ros2_control>', '', s, flags=re.DOTALL)
open(path, 'w').write(s)
PY

echo "[build_urdf] wrote ${URDF_OUT}"
