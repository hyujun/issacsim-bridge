"""Newton ArticulationView setup + YAML-joint-name -> DOF-index map."""

import carb
import isaacsim.physics.newton as newton_ext
from isaacsim.physics.newton import tensors as newton_tensors

from sim_bridge.config import ROBOT_CFG
from sim_bridge.dof_map import build_dof_index_map
from sim_bridge.robot import find_articulation_root_path


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

    index_map = build_dof_index_map(list(ROBOT_CFG["joint_names"]), dof_names)

    carb.log_warn(
        f"[launch_sim] Newton articulation ready: count={art.count} "
        f"max_dofs={art.max_dofs} dof_names={dof_names}"
    )
    return sim_view, art, index_map
