"""Robot pack + robot.yaml loader.

Safe to import before SimulationApp is up — only stdlib + yaml.

Exposes two layers:

* Pure functions `load_robot_config(pack_path)` / `compute_sim_config(cfg)` —
  no filesystem side effect at import time, testable on host without a real
  pack.
* Module-level `ROBOT_PACK` / `ROBOT_CFG` / `SIM_CFG` — legacy convenience
  for launch_sim.py and isaacsim_bridge submodules. Loaded lazily on first access
  via module-level `__getattr__`, so importing this module on a host that
  doesn't have the default pack on disk (e.g. pytest on the host) no longer
  fails — only accessing the constants triggers the load.
"""

import os
from pathlib import Path

import yaml

_SIM_DEFAULTS = {
    "mode": "freerun",          # "freerun" | "sync"
    "substeps": 4,              # physics_dt = rendering_dt / substeps
    "render_rate_hz": 60,       # maybe_render() wall-clock cadence (sync)
    "step_rate_hz": 500,        # sync: rendering_dt = 1/step_rate_hz (sim-time per step)
    "sync_timeout_s": 0.5,      # sync: wall-clock heartbeat when /joint_command idle
}


def default_pack_path() -> Path:
    """Return ROBOT_PACK from env, or the in-container default."""
    return Path(os.environ.get("ROBOT_PACK", "/workspace/robots/ur5e"))


def load_robot_config(pack_path: Path) -> dict:
    """Parse `<pack_path>/robot.yaml` and return the dict verbatim.

    Raises FileNotFoundError if the yaml is missing — caller decides how to
    handle. We don't validate fields here; `compute_sim_config` handles the
    one cross-cutting check (sim.mode).
    """
    cfg_path = Path(pack_path) / "robot.yaml"
    with cfg_path.open() as fh:
        return yaml.safe_load(fh)


def compute_sim_config(robot_cfg: dict) -> dict:
    """Merge robot.yaml `sim:` section with defaults. Validates sim.mode.

    Older robot.yaml without a `sim:` section still works — everything falls
    back to freerun with legacy dt (1/60 render, 1/240 physics = 4 substeps
    per step), matching historical behavior.
    """
    sim_cfg = {**_SIM_DEFAULTS, **(robot_cfg.get("sim") or {})}
    if sim_cfg["mode"] not in ("freerun", "sync"):
        raise ValueError(
            f"robot.yaml sim.mode must be 'freerun' or 'sync', got {sim_cfg['mode']!r}"
        )
    return sim_cfg


# ---- Lazy module-level constants (legacy convenience) ----

_LAZY_CACHE: dict = {}

# Static type annotations so downstream imports see narrow types (dict / Path)
# instead of the wide `Any` inferred from module-level `__getattr__`.
ROBOT_PACK: Path
ROBOT_CFG: dict
SIM_CFG: dict


def __getattr__(name: str):
    if name == "ROBOT_PACK":
        if "ROBOT_PACK" not in _LAZY_CACHE:
            _LAZY_CACHE["ROBOT_PACK"] = default_pack_path()
        return _LAZY_CACHE["ROBOT_PACK"]
    if name == "ROBOT_CFG":
        if "ROBOT_CFG" not in _LAZY_CACHE:
            _LAZY_CACHE["ROBOT_CFG"] = load_robot_config(default_pack_path())
        return _LAZY_CACHE["ROBOT_CFG"]
    if name == "SIM_CFG":
        if "SIM_CFG" not in _LAZY_CACHE:
            _LAZY_CACHE["SIM_CFG"] = compute_sim_config(load_robot_config(default_pack_path()))
        return _LAZY_CACHE["SIM_CFG"]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
