"""Pure-Python DOF name <-> index utilities.

Split out of newton_view.py so host-side tests can import this without
pulling in `isaacsim.physics.newton` (which only resolves inside the
Isaac Sim container).
"""


def build_dof_index_map(yaml_names: list[str], newton_dof_names: list[str]) -> dict[str, int]:
    """Map each yaml joint name to its index in Newton's flat DOF list.

    Accepts either a plain name match (`shoulder_pan_joint`) or a path-suffix
    match (`/World/Robot/.../shoulder_pan_joint`) — Newton's dof_names can be
    full USD paths depending on articulation layout. Raises RuntimeError with
    the full available-names list if any yaml_name is unmatched.
    """
    index_map: dict[str, int] = {}
    for yaml_name in yaml_names:
        found = None
        for i, n in enumerate(newton_dof_names):
            if n == yaml_name or n.rsplit("/", 1)[-1] == yaml_name:
                found = i
                break
        if found is None:
            raise RuntimeError(
                f"DOF '{yaml_name}' not found in Newton articulation. "
                f"Available DOFs: {newton_dof_names}"
            )
        index_map[yaml_name] = found
    return index_map
