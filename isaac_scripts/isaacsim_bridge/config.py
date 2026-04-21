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


_REQUIRED_FIELDS: tuple[tuple[str, ...], ...] = (
    ("robot", "urdf_rel"),
    ("robot", "usd_rel"),
    ("robot", "prim_path"),
    ("robot", "root_link"),
    ("joint_names",),
    ("drive", "mode"),
    ("drive", "stiffness"),
    ("drive", "damping"),
    ("ros", "joint_states_topic"),
    ("ros", "joint_command_topic"),
)


def _get_nested(d: dict, path: tuple[str, ...]):
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return _MISSING
        cur = cur[key]
    return cur


_MISSING = object()


def validate_robot_config(cfg: dict, pack_path: Path | None = None) -> None:
    """Validate robot.yaml shape. Raises ValueError listing every issue.

    Caller gets all problems in one shot — no drip-feed of KeyError.
    `pack_path` enables on-disk checks (urdf_rel / usd_rel existence); pass
    None to skip (useful in unit tests with synthetic configs).
    """
    errors: list[str] = []

    for path in _REQUIRED_FIELDS:
        val = _get_nested(cfg, path)
        if val is _MISSING:
            errors.append(f"missing required field: {'.'.join(path)}")
        elif path == ("joint_names",):
            if not isinstance(val, list) or not val:
                errors.append("joint_names must be a non-empty list")

    drive = cfg.get("drive") or {}
    if isinstance(drive, dict) and drive.get("mode") not in (None, "position"):
        errors.append(f"drive.mode must be 'position' (got {drive['mode']!r})")

    if pack_path is not None:
        robot = cfg.get("robot") or {}
        if isinstance(robot, dict):
            urdf_rel = robot.get("urdf_rel")
            if isinstance(urdf_rel, str) and not (Path(pack_path) / urdf_rel).is_file():
                errors.append(f"robot.urdf_rel not found: {pack_path}/{urdf_rel}")

    if errors:
        preamble = f"robot.yaml validation failed ({len(errors)} issue(s))"
        if pack_path is not None:
            preamble += f" in {pack_path}"
        raise ValueError(preamble + ":\n  - " + "\n  - ".join(errors))


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
            pack = default_pack_path()
            cfg = load_robot_config(pack)
            validate_robot_config(cfg, pack)
            _LAZY_CACHE["ROBOT_CFG"] = cfg
        return _LAZY_CACHE["ROBOT_CFG"]
    if name == "SIM_CFG":
        if "SIM_CFG" not in _LAZY_CACHE:
            pack = default_pack_path()
            cfg = load_robot_config(pack)
            validate_robot_config(cfg, pack)
            _LAZY_CACHE["SIM_CFG"] = compute_sim_config(cfg)
        return _LAZY_CACHE["SIM_CFG"]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
