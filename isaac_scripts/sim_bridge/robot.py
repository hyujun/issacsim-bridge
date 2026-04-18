"""Robot lifecycle: World construction, USD reference, articulation-root
discovery, Newton backend assertion.
"""

import carb
from isaacsim.core.api import World
from isaacsim.core.utils.stage import add_reference_to_stage, get_current_stage
from pxr import Usd, UsdPhysics

from sim_bridge.config import ROBOT_CFG, ROBOT_PACK, SIM_CFG


def build_world() -> World:
    # rendering_dt is the sim-time advanced per world.step() call (Isaac naming
    # predates render/physics decoupling — it is NOT the render Hz).
    #   freerun: one step = 1/render_rate_hz sim-time, step_rate_hz unused.
    #   sync:    one step = 1/step_rate_hz sim-time; maybe_render() owns the
    #            actual render cadence via simulation_app.update().
    substeps = int(SIM_CFG["substeps"])
    if SIM_CFG["mode"] == "sync":
        rendering_dt = 1.0 / float(SIM_CFG["step_rate_hz"])
    else:
        rendering_dt = 1.0 / float(SIM_CFG["render_rate_hz"])
    physics_dt = rendering_dt / substeps

    carb.log_warn(
        f"[launch_sim] World dt: mode={SIM_CFG['mode']} "
        f"rendering_dt={rendering_dt:.6g}s physics_dt={physics_dt:.6g}s "
        f"substeps={substeps}"
    )

    world = World(
        stage_units_in_meters=1.0,
        physics_dt=physics_dt,
        rendering_dt=rendering_dt,
        backend="torch",
        device="cuda:0",
    )
    world.scene.add_default_ground_plane()
    return world


def load_robot() -> str:
    usd_path = str(ROBOT_PACK / ROBOT_CFG["robot"]["usd_rel"])
    prim_path = ROBOT_CFG["robot"]["prim_path"]
    add_reference_to_stage(usd_path=usd_path, prim_path=prim_path)
    carb.log_warn(f"[launch_sim] Robot referenced: {usd_path} -> {prim_path}")
    return prim_path


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
