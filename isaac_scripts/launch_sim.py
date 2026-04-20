"""Isaac Sim bootstrap: Newton physics + ROS 2 bridge + robot articulation.

Robot-agnostic. Loads a "robot pack" from $ROBOT_PACK (defaults to
/workspace/robots/ur5e). See docs/ROBOTS.md for the pack contract.

This entry owns SimulationApp bring-up and orchestration only. All runtime
logic lives in the `sim_bridge/` package next to this file. Submodules are
imported AFTER SimulationApp is up so they can freely import pxr / kit.

Env flags:
    SIM_HEADLESS=1            run without a GUI window (for CI/smoke tests).
    SIM_SKIP_PATCHES=<csv>    comma-separated patch names to skip — used by
                              Phase 1.2 per-patch validation. Valid names:
                              repair_joint_chain, apply_drive_gains.
    SIM_MAX_RUN_SECONDS=<n>   auto-close after n wall-clock seconds (smoke
                              test harness). 0/unset = run until GUI close.
"""

import os
import warnings

# Third-party UserWarning/DeprecationWarning that Newton and warp emit to
# stderr end up tagged `[Error] [py stderr]` by carb's stderr capture. Filter
# the known-noisy sources before SimulationApp boots Python's warning system.
# Keep patterns narrow so sim_bridge/* warnings still surface.
warnings.filterwarnings("ignore", category=UserWarning, module=r"newton\._src\..*")
warnings.filterwarnings("ignore", category=UserWarning, module=r"warp\..*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"warp\..*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=r".*pxr\.Semantics is deprecated.*")

from isaacsim import SimulationApp

_HEADLESS = os.environ.get("SIM_HEADLESS", "0") not in ("0", "", "false", "False")
_SKIP_PATCHES = {s.strip() for s in os.environ.get("SIM_SKIP_PATCHES", "").split(",") if s.strip()}
_MAX_RUN_SECONDS = float(os.environ.get("SIM_MAX_RUN_SECONDS", "0") or 0)

CONFIG = {
    "headless": _HEADLESS,
    "renderer": "RaytracedLighting",
    "width": 1280,
    "height": 720,
}

# 6.0.0-dev2 defaults to isaacsim.exp.full.streaming.kit which blocks on a
# WebRTC client. Force the Newton-preconfigured desktop experience.
EXPERIENCE = "/isaac-sim/apps/isaacsim.exp.full.newton.kit"

simulation_app = SimulationApp(CONFIG, experience=EXPERIENCE)

from isaacsim.core.utils.extensions import enable_extension  # noqa: E402

enable_extension("isaacsim.physics.newton")
enable_extension("isaacsim.ros2.bridge")
enable_extension("isaacsim.core.nodes")

simulation_app.update()

import carb  # noqa: E402

from sim_bridge.config import ROBOT_CFG, ROBOT_PACK  # noqa: E402
from sim_bridge.main_loop import run  # noqa: E402
from sim_bridge.newton_view import setup_newton_articulation  # noqa: E402
from sim_bridge.robot import assert_newton_backend, build_world, load_robot  # noqa: E402
from sim_bridge.ros_bridge import setup_clock_publisher, setup_rclpy_bridge  # noqa: E402
from sim_bridge.usd_patches import (  # noqa: E402
    apply_drive_gains_to_joints,
    repair_joint_chain,
)

carb.log_warn(f"[launch_sim] Loading robot pack: {ROBOT_PACK}")
if _SKIP_PATCHES:
    carb.log_warn(f"[launch_sim] SIM_SKIP_PATCHES active — skipping: {sorted(_SKIP_PATCHES)}")
world = build_world()
art_root = load_robot()

# Each USD patch can be suppressed independently via SIM_SKIP_PATCHES (Phase 1.2
# per-patch validation harness). Patch names match the module function names.
_PATCHES = [
    ("repair_joint_chain", lambda: repair_joint_chain(art_root, ROBOT_CFG["robot"]["root_link"])),
    ("apply_drive_gains",  lambda: apply_drive_gains_to_joints(art_root)),
]
for _name, _fn in _PATCHES:
    if _name in _SKIP_PATCHES:
        carb.log_warn(f"[launch_sim] SKIPPED patch: {_name}")
        continue
    _fn()

world.reset()  # creates physics scene + registers articulation before graph wiring
setup_clock_publisher()
sim_view, articulation, dof_index_map = setup_newton_articulation(art_root)
ros_node, js_pub, latest_cmd = setup_rclpy_bridge()
world.play()  # OnPlaybackTick only fires while timeline is playing
assert_newton_backend()

carb.log_warn("[launch_sim] Newton + ROS2 bridge + robot bootstrap complete. Running simulation loop.")
if _MAX_RUN_SECONDS > 0:
    carb.log_warn(f"[launch_sim] SIM_MAX_RUN_SECONDS={_MAX_RUN_SECONDS}s — will self-close when elapsed")
run(
    simulation_app, world, articulation, dof_index_map, ros_node, js_pub, latest_cmd,
    max_run_seconds=_MAX_RUN_SECONDS,
)
