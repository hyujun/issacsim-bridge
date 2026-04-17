"""Isaac Sim bootstrap: Newton physics + ROS 2 bridge + robot articulation.

Robot-agnostic. Loads a "robot pack" from $ROBOT_PACK (defaults to
/workspace/robots/ur5e). See docs/ROBOTS.md for the pack contract.

Runtime responsibilities:
  - Bring up Newton physics and the ROS 2 bridge extension.
  - Reference the robot USD into the stage at pack.prim_path.
  - Publish /clock from the bridge OmniGraph.
  - Publish JointState and apply received position commands via a rclpy
    sidechannel that writes to UsdPhysics DriveAPI/JointStateAPI attributes.
    (The PhysX-tensor OmniGraph joint nodes SEGV on URDFImporter output in
    Isaac Sim 6.0.0-dev2; see docs/TROUBLESHOOTING.md.)
"""

import math
import os
import time
from pathlib import Path

import yaml

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

import carb
from isaacsim.core.utils.extensions import enable_extension

enable_extension("isaacsim.physics.newton")
enable_extension("isaacsim.ros2.bridge")
enable_extension("isaacsim.core.nodes")

simulation_app.update()

from isaacsim.core.api import World
from isaacsim.core.utils.stage import add_reference_to_stage, get_current_stage
from pxr import Usd, UsdPhysics

import rclpy
from sensor_msgs.msg import JointState

ROBOT_PACK = Path(os.environ.get("ROBOT_PACK", "/workspace/robots/ur5e"))
ROBOT_CFG_PATH = ROBOT_PACK / "robot.yaml"
with ROBOT_CFG_PATH.open() as fh:
    ROBOT_CFG = yaml.safe_load(fh)

world = World(
    stage_units_in_meters=1.0,
    physics_dt=1.0 / 400.0,
    rendering_dt=1.0 / 60.0,
    backend="torch",
    device="cuda:0",
)
world.scene.add_default_ground_plane()


def assert_newton_backend() -> None:
    stage: Usd.Stage = get_current_stage()
    scene_prim = None
    for prim in stage.Traverse():
        if prim.IsA(UsdPhysics.Scene):
            scene_prim = prim
            break

    if scene_prim is None:
        carb.log_warn("No UsdPhysics.Scene prim found; cannot verify Newton backend.")
        return

    physx_scene_api_attrs = {a.GetName(): a for a in scene_prim.GetAttributes()}
    solver_attr = physx_scene_api_attrs.get("physxScene:solverType")
    backend_attr = physx_scene_api_attrs.get("physics:backend")

    reported = []
    if solver_attr is not None:
        reported.append(f"physxScene:solverType={solver_attr.Get()}")
    if backend_attr is not None:
        reported.append(f"physics:backend={backend_attr.Get()}")

    carb.log_warn(f"[PhysicsBackendCheck] {', '.join(reported) or 'no backend attrs exposed'}")


def load_robot() -> str:
    usd_path = str(ROBOT_PACK / ROBOT_CFG["robot"]["usd_rel"])
    prim_path = ROBOT_CFG["robot"]["prim_path"]
    add_reference_to_stage(usd_path=usd_path, prim_path=prim_path)
    carb.log_warn(f"[launch_sim] Robot referenced: {usd_path} -> {prim_path}")
    return prim_path


def setup_clock_publisher() -> None:
    import omni.graph.core as og

    keys = og.Controller.Keys
    og.Controller.edit(
        {"graph_path": "/World/ROS2ClockGraph", "evaluator_name": "execution"},
        {
            keys.CREATE_NODES: [
                ("OnPlaybackTick", "omni.graph.action.OnPlaybackTick"),
                ("ReadSimTime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
                ("PublishClock", "isaacsim.ros2.bridge.ROS2PublishClock"),
            ],
            keys.CONNECT: [
                ("OnPlaybackTick.outputs:tick", "PublishClock.inputs:execIn"),
                ("ReadSimTime.outputs:simulationTime", "PublishClock.inputs:timeStamp"),
            ],
            keys.SET_VALUES: [
                ("PublishClock.inputs:topicName", "/clock"),
            ],
        },
    )


def setup_joint_drives(art_root: str) -> tuple[dict, dict]:
    """Configure PD drive on each revolute joint and return (drives, states) maps.

    USD DriveAPI/JointStateAPI is used instead of Isaac's PhysX-tensor Articulation
    wrapper because that path SEGVs on URDFImporter output under Newton.
    """
    stage: Usd.Stage = get_current_stage()
    drive_cfg = ROBOT_CFG["drive"]
    stiffness = float(drive_cfg["stiffness"])
    damping = float(drive_cfg["damping"])
    joints_subpath = ROBOT_CFG["robot"].get("joints_subpath", "Physics")

    drives: dict = {}
    states: dict = {}
    for name in ROBOT_CFG["joint_names"]:
        joint_path = f"{art_root}/{joints_subpath}/{name}"
        prim = stage.GetPrimAtPath(joint_path)
        if not prim.IsValid():
            raise RuntimeError(f"Joint prim not found: {joint_path}")
        drive = UsdPhysics.DriveAPI.Get(prim, "angular")
        state = UsdPhysics.JointStateAPI.Get(prim, "angular")
        drive.CreateStiffnessAttr().Set(stiffness)
        drive.CreateDampingAttr().Set(damping)
        drives[name] = drive
        states[name] = state

    carb.log_warn(
        f"[launch_sim] Configured {len(drives)} joint drives (stiffness={stiffness}, damping={damping})"
    )
    return drives, states


def setup_rclpy_bridge() -> tuple:
    """Initialize rclpy, create publisher + subscriber, return (node, pub, latest_cmd)."""
    rclpy.init(args=[])
    node = rclpy.create_node("isaac_sim_bridge")

    js_topic = ROBOT_CFG["ros"]["joint_states_topic"]
    jc_topic = ROBOT_CFG["ros"]["joint_command_topic"]

    js_pub = node.create_publisher(JointState, js_topic, 10)

    # Mutable container: callback mutates; main loop reads and clears.
    latest_cmd: dict = {"names": None, "positions": None}

    def _on_cmd(msg: JointState) -> None:
        latest_cmd["names"] = list(msg.name)
        latest_cmd["positions"] = list(msg.position)

    node.create_subscription(JointState, jc_topic, _on_cmd, 10)

    carb.log_warn(
        f"[launch_sim] rclpy bridge ready: publish {js_topic}, subscribe {jc_topic}"
    )
    return node, js_pub, latest_cmd


carb.log_warn(f"[launch_sim] Loading robot pack: {ROBOT_PACK}")
art_root = load_robot()
world.reset()  # creates physics scene + registers articulation before graph wiring
setup_clock_publisher()
joint_drives, joint_states = setup_joint_drives(art_root)
ros_node, js_pub, latest_cmd = setup_rclpy_bridge()
world.play()  # OnPlaybackTick only fires while timeline is playing
assert_newton_backend()

carb.log_warn("[launch_sim] Newton + ROS2 bridge + robot bootstrap complete. Running simulation loop.")

pub_interval = 1.0 / float(ROBOT_CFG["ros"]["publish_rate_hz"])
next_pub_time = 0.0
joint_names = list(ROBOT_CFG["joint_names"])

try:
    while simulation_app.is_running():
        world.step(render=True)

        cmd_positions = latest_cmd["positions"]
        if cmd_positions is not None:
            for name, pos_rad in zip(latest_cmd["names"], cmd_positions):
                drive = joint_drives.get(name)
                if drive is not None:
                    drive.GetTargetPositionAttr().Set(math.degrees(float(pos_rad)))
            latest_cmd["positions"] = None

        rclpy.spin_once(ros_node, timeout_sec=0.0)

        now = time.monotonic()
        if now >= next_pub_time:
            msg = JointState()
            msg.header.stamp = ros_node.get_clock().now().to_msg()
            msg.name = joint_names
            msg.position = [
                math.radians(float(joint_states[n].GetPositionAttr().Get() or 0.0))
                for n in joint_names
            ]
            js_pub.publish(msg)
            next_pub_time = now + pub_interval
finally:
    ros_node.destroy_node()
    rclpy.shutdown()
    simulation_app.close()
