"""Runtime USD patches for URDFImporter output (Isaac Sim 6.0.0-dev2).

Applied after add_reference_to_stage and before world.reset(), so Newton sees
a corrected stage when it parses articulations.
"""

import carb
from isaacsim.core.utils.stage import get_current_stage
from pxr import Usd, UsdPhysics

from sim_bridge.config import ROBOT_CFG


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
