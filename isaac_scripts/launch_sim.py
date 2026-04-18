"""Isaac Sim bootstrap: Newton physics + ROS 2 bridge + robot articulation.

Robot-agnostic. Loads a "robot pack" from $ROBOT_PACK (defaults to
/workspace/robots/ur5e). See docs/ROBOTS.md for the pack contract.

Runtime responsibilities:
  - Bring up Newton physics (MuJoCo-Warp solver) and the ROS 2 bridge extension.
  - Reference the robot USD into the stage at pack.prim_path.
  - Patch the USD in-place before world.reset():
      * Rewrite each joint's `physics:body0` to the USD parent of its
        `physics:body1`. URDFImporter (6.0.0-dev2) writes body0=<robot root>
        for every joint, which breaks the kinematic chain — Newton then parses
        each link as its own articulation with zero DOFs.
      * Author PD gains onto each revolute joint's UsdPhysics.DriveAPI so
        Newton installs POSITION-mode JOINT_TARGET actuators (URDFImporter
        output ships DriveAPI with only maxForce, which Newton otherwise
        resolves to EFFORT mode and leaves joints un-actuated).
  - Publish /clock from the bridge OmniGraph.
  - Publish JointState and apply received position commands via a rclpy
    sidechannel that talks to Newton's ArticulationView tensor API
    (set_dof_position_targets / get_dof_positions). The PhysX-tensor
    OmniGraph joint nodes SEGV on URDFImporter output in Isaac Sim
    6.0.0-dev2; see docs/TROUBLESHOOTING.md.
"""

import os
import time
from pathlib import Path

import torch
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

import isaacsim.physics.newton as newton_ext
from isaacsim.physics.newton import tensors as newton_tensors

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


def repair_joint_chain(prim_path: str, articulation_root_name: str = "base_link") -> int:
    """Rewrite each joint's `physics:body0` to the USD parent of `physics:body1`.

    URDFImporter (Isaac Sim 6.0.0-dev2) emits every joint with
    `physics:body0 = </ur5e>` (the robot root Xform). That leaves each link
    attached to the root in a star topology, so Newton parses every body as
    its own articulation and the manipulator loses its kinematic chain.

    This walks under `prim_path` and points each joint's body0 at the USD
    parent of its body1. The only exception is the fixed joint whose body1 is
    the articulation root link itself — that one must stay world-anchored.
    """
    stage: Usd.Stage = get_current_stage()
    root = stage.GetPrimAtPath(prim_path)
    if not root.IsValid():
        raise RuntimeError(f"Robot prim not found: {prim_path}")

    joint_types = {
        "PhysicsRevoluteJoint",
        "PhysicsFixedJoint",
        "PhysicsPrismaticJoint",
        "PhysicsSphericalJoint",
        "PhysicsJoint",
    }

    fixed = 0
    skipped_world_anchor = 0
    for prim in Usd.PrimRange(root):
        if prim.GetTypeName() not in joint_types:
            continue
        body0_rel = prim.GetRelationship("physics:body0")
        body1_rel = prim.GetRelationship("physics:body1")
        if not body0_rel or not body1_rel:
            continue
        body1_targets = body1_rel.GetTargets()
        if not body1_targets:
            continue
        body1_path = body1_targets[0]
        # World-anchor exception: joint that binds the articulation root link
        # itself must keep body0 = robot root (treated as world by Newton).
        if body1_path.name == articulation_root_name:
            skipped_world_anchor += 1
            continue
        parent_path = body1_path.GetParentPath()
        body0_rel.SetTargets([parent_path])
        fixed += 1

    carb.log_warn(
        f"[launch_sim] Repaired joint chain: rewrote body0 on {fixed} joints, "
        f"kept {skipped_world_anchor} world-anchor joint(s)"
    )
    return fixed


def apply_drive_gains_to_joints(prim_path: str) -> int:
    """Author UsdPhysics.DriveAPI stiffness/damping on every revolute joint
    under the robot BEFORE Newton parses the stage.

    URDFImporter emits DriveAPI:angular with only `drive:...:maxForce`.
    Newton's `JointTargetMode.from_gains(ke=0, kd=0, has_drive=True)` then
    resolves to EFFORT mode, which installs a CTRL_DIRECT motor actuator that
    subsequently fails target resolution in solver_mujoco._init_actuators and
    leaves the joint un-actuated. Setting stiffness > 0 here promotes the mode
    to POSITION and Newton installs a proper PD servo bound to
    control.joint_target_pos (driven by NewtonArticulationView below).
    """
    stage: Usd.Stage = get_current_stage()
    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        raise RuntimeError(f"Robot prim not found: {prim_path}")
    drive_cfg = ROBOT_CFG["drive"]
    stiffness = float(drive_cfg["stiffness"])
    damping = float(drive_cfg["damping"])

    count = 0
    for prim in Usd.PrimRange(root_prim):
        if prim.GetTypeName() != "PhysicsRevoluteJoint":
            continue
        drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
        drive.CreateStiffnessAttr().Set(stiffness)
        drive.CreateDampingAttr().Set(damping)
        count += 1
    carb.log_warn(
        f"[launch_sim] Patched {count} revolute joints with "
        f"stiffness={stiffness}, damping={damping}"
    )
    return count


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


def find_articulation_root_path(robot_prim_path: str) -> str:
    """Locate the prim with PhysicsArticulationRootAPI under the robot root.

    URDFImporter attaches ArticulationRootAPI to the kinematic base link
    (e.g. `/World/Robot/Geometry/world/base_link`), not the reference anchor
    (`/World/Robot`). Newton's articulation_label matches the API-bearing prim,
    so the tensor view pattern must point there.
    """
    stage: Usd.Stage = get_current_stage()
    root = stage.GetPrimAtPath(robot_prim_path)
    if not root.IsValid():
        raise RuntimeError(f"Robot prim not found: {robot_prim_path}")
    for prim in Usd.PrimRange(root):
        schemas = prim.GetAppliedSchemas()
        if "PhysicsArticulationRootAPI" in schemas or "NewtonArticulationRootAPI" in schemas:
            return str(prim.GetPath())
    raise RuntimeError(
        f"No PhysicsArticulationRootAPI / NewtonArticulationRootAPI prim under {robot_prim_path}"
    )


def setup_newton_articulation(prim_path: str) -> tuple:
    """Build a Newton tensor ArticulationView and a joint-name -> DOF-index map.

    Commands and joint state go through Newton's unified Control struct
    (set_dof_position_targets / get_dof_positions). The matching PD gains were
    already authored onto USD joints in apply_drive_gains_to_joints, so Newton
    installed POSITION-mode JOINT_TARGET actuators at parse time.
    """
    newton_stage = newton_ext.acquire_stage()
    sim_view = newton_tensors.create_simulation_view("torch", newton_stage)

    art_root_path = find_articulation_root_path(prim_path)
    carb.log_warn(f"[launch_sim] Articulation root prim (USD): {art_root_path}")

    try:
        known_labels = list(newton_stage.model.articulation_label)
    except Exception as e:
        known_labels = f"<unavailable: {e}>"
    carb.log_warn(f"[launch_sim] Newton model articulations: {known_labels}")

    # Prefer an exact label match if the API-bearing prim matches a Newton articulation_label.
    # Otherwise fall back to the first non-empty articulation in the model, which is typically
    # what URDFImporter produces when the ArticulationRootAPI prim differs from Newton's root.
    pattern = art_root_path
    if isinstance(known_labels, list) and art_root_path not in known_labels and known_labels:
        pattern = known_labels[0]
        carb.log_warn(
            f"[launch_sim] ArticulationRootAPI prim {art_root_path} not in Newton labels; "
            f"falling back to {pattern}"
        )

    art = sim_view.create_articulation_view(pattern)

    if art.count == 0:
        raise RuntimeError(
            f"Newton ArticulationView matched no articulations for pattern {pattern!r}. "
            f"Known labels: {known_labels}"
        )
    if art.count > 1:
        carb.log_warn(f"[launch_sim] {art.count} articulations matched; using index 0")

    dof_names_nested = art.dof_names  # list[list[str]]
    dof_paths_nested = art.dof_paths
    carb.log_warn(
        f"[launch_sim] ArticulationView count={art.count} max_dofs={art.max_dofs} "
        f"dof_names={dof_names_nested} dof_paths={dof_paths_nested}"
    )
    dof_names = list(dof_names_nested[0]) if dof_names_nested else []

    index_map: dict[str, int] = {}
    for yaml_name in ROBOT_CFG["joint_names"]:
        found = None
        for i, n in enumerate(dof_names):
            if n == yaml_name or n.rsplit("/", 1)[-1] == yaml_name:
                found = i
                break
        if found is None:
            raise RuntimeError(
                f"DOF '{yaml_name}' not found in Newton articulation. Available DOFs: {dof_names}"
            )
        index_map[yaml_name] = found

    carb.log_warn(
        f"[launch_sim] Newton articulation ready: count={art.count} "
        f"max_dofs={art.max_dofs} dof_names={dof_names}"
    )
    return sim_view, art, index_map


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
repair_joint_chain(art_root)
apply_drive_gains_to_joints(art_root)
world.reset()  # creates physics scene + registers articulation before graph wiring
setup_clock_publisher()
sim_view, articulation, dof_index_map = setup_newton_articulation(art_root)
ros_node, js_pub, latest_cmd = setup_rclpy_bridge()
world.play()  # OnPlaybackTick only fires while timeline is playing
assert_newton_backend()

carb.log_warn("[launch_sim] Newton + ROS2 bridge + robot bootstrap complete. Running simulation loop.")

pub_interval = 1.0 / float(ROBOT_CFG["ros"]["publish_rate_hz"])
next_pub_time = 0.0
joint_names = list(ROBOT_CFG["joint_names"])
_device = torch.device("cuda:0")
indices0 = torch.tensor([0], dtype=torch.int32, device=_device)
target_buffer = torch.zeros((1, articulation.max_dofs), dtype=torch.float32, device=_device)

try:
    while simulation_app.is_running():
        world.step(render=True)

        cmd_positions = latest_cmd["positions"]
        if cmd_positions is not None:
            # Seed from current targets so unlisted DOFs keep their last commanded value.
            target_buffer.copy_(articulation.get_dof_position_targets(copy=True))
            for name, pos_rad in zip(latest_cmd["names"], cmd_positions):
                idx = dof_index_map.get(name)
                if idx is not None:
                    target_buffer[0, idx] = float(pos_rad)
            articulation.set_dof_position_targets(target_buffer, indices0)
            latest_cmd["positions"] = None

        rclpy.spin_once(ros_node, timeout_sec=0.0)

        now = time.monotonic()
        if now >= next_pub_time:
            positions = articulation.get_dof_positions(copy=True).detach().cpu().numpy()
            msg = JointState()
            msg.header.stamp = ros_node.get_clock().now().to_msg()
            msg.name = joint_names
            msg.position = [float(positions[0, dof_index_map[n]]) for n in joint_names]
            js_pub.publish(msg)
            next_pub_time = now + pub_interval
finally:
    ros_node.destroy_node()
    rclpy.shutdown()
    simulation_app.close()
