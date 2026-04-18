"""Robot pack + robot.yaml loader.

Safe to import before SimulationApp is up — only stdlib + yaml.
"""

import os
from pathlib import Path

import yaml

ROBOT_PACK = Path(os.environ.get("ROBOT_PACK", "/workspace/robots/ur5e"))
ROBOT_CFG_PATH = ROBOT_PACK / "robot.yaml"

with ROBOT_CFG_PATH.open() as fh:
    ROBOT_CFG = yaml.safe_load(fh)

# Sim-mode config with defaults. Older robot.yaml without a `sim:` section
# still works — everything falls back to freerun with legacy dt (1/60 render,
# 1/240 physics = 4 substeps per step), matching historical behavior.
_SIM_DEFAULTS = {
    "mode": "freerun",          # "freerun" | "sync"
    "substeps": 4,              # physics_dt = rendering_dt / substeps
    "render_rate_hz": 60,       # maybe_render() wall-clock cadence (sync)
    "step_rate_hz": 500,        # sync: rendering_dt = 1/step_rate_hz (sim-time per step)
    "sync_timeout_s": 0.5,      # sync: wall-clock heartbeat when /joint_command idle
}
SIM_CFG = {**_SIM_DEFAULTS, **(ROBOT_CFG.get("sim") or {})}

if SIM_CFG["mode"] not in ("freerun", "sync"):
    raise ValueError(
        f"robot.yaml sim.mode must be 'freerun' or 'sync', got {SIM_CFG['mode']!r}"
    )
