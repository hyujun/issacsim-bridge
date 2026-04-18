"""Isaac Sim bootstrap: Newton physics + ROS 2 bridge + robot articulation.

Robot-agnostic. Loads a "robot pack" from $ROBOT_PACK (defaults to
/workspace/robots/ur5e). See docs/ROBOTS.md for the pack contract.

This entry owns SimulationApp bring-up and orchestration only. All runtime
logic lives in the `sim_bridge/` package next to this file. Submodules are
imported AFTER SimulationApp is up so they can freely import pxr / kit.
"""

from isaacsim import SimulationApp

CONFIG = {
    "headless": False,
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

from sim_bridge.config import ROBOT_PACK  # noqa: E402
from sim_bridge.main_loop import run  # noqa: E402
from sim_bridge.newton_view import setup_newton_articulation  # noqa: E402
from sim_bridge.robot import assert_newton_backend, build_world, load_robot  # noqa: E402
from sim_bridge.ros_bridge import setup_clock_publisher, setup_rclpy_bridge  # noqa: E402
from sim_bridge.usd_patches import apply_drive_gains_to_joints, repair_joint_chain  # noqa: E402

carb.log_warn(f"[launch_sim] Loading robot pack: {ROBOT_PACK}")
world = build_world()
art_root = load_robot()
repair_joint_chain(art_root)
apply_drive_gains_to_joints(art_root)
world.reset()  # creates physics scene + registers articulation before graph wiring
setup_clock_publisher()
sim_view, articulation, dof_index_map = setup_newton_articulation(art_root)
ros_node, js_pub, latest_cmd = setup_rclpy_bridge()
world.play()  # OnPlaybackTick only fires while timeline is playing
assert_newton_backend()

carb.log_warn("[launch_sim] Newton + ROS2 bridge + robot bootstrap complete. Running simulation loop.")
run(simulation_app, world, articulation, dof_index_map, ros_node, js_pub, latest_cmd)
