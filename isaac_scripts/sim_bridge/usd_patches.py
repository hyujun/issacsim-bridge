"""Runtime USD patches for URDFImporter output (Isaac Sim 6.0.0-dev2).

Applied after add_reference_to_stage and before world.reset(), so Newton sees
a corrected stage when it parses articulations.
"""

import carb
from isaacsim.core.utils.stage import get_current_stage
from pxr import Usd, UsdPhysics

from sim_bridge.config import ROBOT_CFG


def repair_joint_chain(prim_path: str, articulation_root_name: str) -> int:
    """Rewrite each joint's `physics:body0` to the USD parent of `physics:body1`.

    URDFImporter (Isaac Sim 6.0.0-dev2) emits every joint with `physics:body0`
    pointing at the robot root Xform. That leaves each link attached to the
    root in a star topology, so Newton parses every body as its own
    articulation and the manipulator loses its kinematic chain.

    This walks under `prim_path` and points each joint's body0 at the USD
    parent of its body1. The only exception is the fixed joint whose body1 is
    the articulation root link (`articulation_root_name`, from robot.yaml
    `robot.root_link`) — that one must stay anchored to the robot root so
    Newton treats it as the world-anchor.
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


def strip_zero_mass_api(prim_path: str) -> int:
    """Remove PhysicsMassAPI from virtual links with neither mass nor inertia.

    URDFImporter (Isaac Sim 6.0.0-dev2) applies `PhysicsMassAPI` to every link,
    including URDF virtual/frame links (`base_link`, `ft_frame`, `flange`,
    `tool0`, `base`) that have no `<inertial>` block. Those prims end up with
    mass=0 and diagonalInertia=(0,0,0) but still carry MassAPI, which triggers
    Newton's `Body ... has zero mass and zero inertia despite having the MassAPI
    USD schema applied` UserWarning once per prim at import time.

    Newton falls back to defaults for uninstrumented prims, so removing the
    empty MassAPI is semantically a no-op — it just silences the warning.
    """
    stage: Usd.Stage = get_current_stage()
    root = stage.GetPrimAtPath(prim_path)
    if not root.IsValid():
        raise RuntimeError(f"Robot prim not found: {prim_path}")

    removed = 0
    for prim in Usd.PrimRange(root):
        if not prim.HasAPI(UsdPhysics.MassAPI):
            continue
        mass_attr = prim.GetAttribute("physics:mass")
        inertia_attr = prim.GetAttribute("physics:diagonalInertia")
        mass_val = mass_attr.Get() if mass_attr and mass_attr.HasAuthoredValue() else 0.0
        inertia_val = inertia_attr.Get() if inertia_attr and inertia_attr.HasAuthoredValue() else (0.0, 0.0, 0.0)
        if float(mass_val or 0.0) > 0.0:
            continue
        if any(float(c) > 0.0 for c in (inertia_val or (0.0, 0.0, 0.0))):
            continue
        prim.RemoveAPI(UsdPhysics.MassAPI)
        removed += 1

    carb.log_warn(f"[launch_sim] Stripped empty PhysicsMassAPI from {removed} prim(s)")
    return removed


def populate_robot_schema_links(prim_path: str) -> int:
    """Rebuild `isaac:physics:robotLinks` + IsaacLinkAPI on the robot prim.

    URDFImporter authors `IsaacRobotAPI` on the robot root with a stale
    `isaac:physics:robotLinks` relationship — stale because `ApplyRobotAPI`
    runs at import time when joints still carry the star topology, so the
    BFS only reaches a subset of links. `isaacsim.robot.schema` then emits
    `Robot at ... has links missing from schema relationship` at runtime.

    Re-runs `PopulateRobotSchemaFromArticulation` AFTER `repair_joint_chain`
    so the BFS walks the full kinematic chain and the relationship matches
    `_discover_articulation_prims`'s view of the articulation. Purely a
    log-noise fix — nothing in Newton's simulation path consumes this schema.
    """
    stage: Usd.Stage = get_current_stage()
    root = stage.GetPrimAtPath(prim_path)
    if not root.IsValid():
        raise RuntimeError(f"Robot prim not found: {prim_path}")

    from usd.schema.isaac.robot_schema import utils as robot_schema_utils

    root_link, _ = robot_schema_utils.PopulateRobotSchemaFromArticulation(stage, root, root)
    rel = root.GetRelationship("isaac:physics:robotLinks")
    count = len(rel.GetTargets()) if rel else 0
    carb.log_warn(
        f"[launch_sim] Repopulated robot schema links: "
        f"root={root_link.GetPath() if root_link else '?'}, "
        f"robotLinks targets={count}"
    )
    return count


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

    Mimic followers (joints whose applied schemas include NewtonMimicAPI or
    PhysxMimicJointAPI:*, authored by URDFImporter from URDF `<mimic>`) are
    skipped: their position is determined by the solver-level mimic constraint
    (joint0 = coef0 + coef1 * joint1). A PD drive on the follower would fight
    that constraint with a stale target and cause drift under load. Drives
    belong on leader joints only.

    Both schemas are checked because URDFImporter writes a variant set with
    per-backend payloads — the default "physx" variant deletes NewtonMimicAPI
    and substitutes PhysxMimicJointAPI:rotY. Newton's USD importer reads
    either, so either presence means the joint is a mimic follower.
    """
    stage: Usd.Stage = get_current_stage()
    root_prim = stage.GetPrimAtPath(prim_path)
    if not root_prim.IsValid():
        raise RuntimeError(f"Robot prim not found: {prim_path}")
    drive_cfg = ROBOT_CFG["drive"]
    stiffness = float(drive_cfg["stiffness"])
    damping = float(drive_cfg["damping"])

    count = 0
    skipped_mimic = 0
    for prim in Usd.PrimRange(root_prim):
        if prim.GetTypeName() != "PhysicsRevoluteJoint":
            continue
        applied = prim.GetAppliedSchemas()
        if any(s == "NewtonMimicAPI" or s.startswith("PhysxMimicJointAPI") for s in applied):
            skipped_mimic += 1
            continue
        drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
        drive.CreateStiffnessAttr().Set(stiffness)
        drive.CreateDampingAttr().Set(damping)
        count += 1
    carb.log_warn(
        f"[launch_sim] Patched {count} revolute joints with "
        f"stiffness={stiffness}, damping={damping} "
        f"(skipped {skipped_mimic} mimic follower(s))"
    )
    return count
