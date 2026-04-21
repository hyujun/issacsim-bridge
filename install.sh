#!/usr/bin/env bash
# Host prerequisites for Isaac Sim + ROS 2 bridge on Ubuntu 24.04.
set -euo pipefail

log()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

log "Checking NVIDIA driver"
require_cmd nvidia-smi
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader

log "Checking Docker"
if ! command -v docker >/dev/null 2>&1; then
  warn "docker not installed — installing Docker Engine from docker.com apt repo"
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
fi

if ! getent group docker | grep -qw "${USER}"; then
  warn "adding ${USER} to docker group — you must log out / back in (or run 'newgrp docker') for it to take effect"
  sudo usermod -aG docker "${USER}"
fi

if ! docker info >/dev/null 2>&1; then
  die "docker daemon not reachable — start the service or re-login to pick up group membership"
fi

log "Checking docker compose plugin"
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing"

log "Checking NVIDIA Container Toolkit"
if ! dpkg -s nvidia-container-toolkit >/dev/null 2>&1; then
  warn "nvidia-container-toolkit not installed — installing via apt"
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
fi

log "Verifying GPU visibility inside a test container"
docker run --rm --gpus all nvcr.io/nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi >/dev/null \
  || die "GPU not visible in containers — check nvidia-container-toolkit install"

log "Granting X11 access to local docker (required for GUI)"
xhost +local:docker >/dev/null

log "Checking NGC login (required to pull isaac-sim image)"
if ! grep -q "nvcr.io" "${HOME}/.docker/config.json" 2>/dev/null; then
  warn "Not logged into nvcr.io. Run: docker login nvcr.io  (username: \$oauthtoken, password: NGC API key)"
fi

# Agnostic host deps: Cyclone DDS RMW (default transport, see ./run.sh).
# Pack-specific host deps (e.g. xacro, ros-*-description) are declared per-pack
# in robots/<name>/host_deps.txt — one apt package per line, blank/# ignored.
# install.sh collects the union across all packs; the container never reads
# these since each pack commits its flattened .urdf.
log "Checking ROS 2 Jazzy for host packages"
if [ ! -d /opt/ros/jazzy ]; then
  warn "ROS 2 Jazzy not found at /opt/ros/jazzy — skipping apt packages."
  warn "Install ROS 2 Jazzy first (https://docs.ros.org/en/jazzy/Installation.html), then re-run ./install.sh"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  mapfile -t PACK_DEPS < <(
    shopt -s nullglob
    for f in "${SCRIPT_DIR}"/robots/*/host_deps.txt; do
      sed -E 's/#.*$//; s/^[[:space:]]+|[[:space:]]+$//g' "$f"
    done | grep -v '^$' | sort -u
  )
  log "Installing Cyclone DDS RMW + ${#PACK_DEPS[@]} pack-declared host package(s): ${PACK_DEPS[*]:-<none>}"
  sudo apt-get install -y \
    ros-jazzy-rmw-cyclonedds-cpp \
    "${PACK_DEPS[@]}"
fi

log "Done. Next: ./build.sh  then  ./run.sh"
