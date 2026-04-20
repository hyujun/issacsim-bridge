"""Host-runnable unit tests for isaacsim_bridge.dof_map."""

import pytest

from isaacsim_bridge.dof_map import build_dof_index_map


def test_exact_name_match():
    yaml_names = ["a", "b", "c"]
    newton_names = ["a", "b", "c"]
    assert build_dof_index_map(yaml_names, newton_names) == {"a": 0, "b": 1, "c": 2}


def test_path_suffix_match():
    """Newton can report dof_names as full USD paths — last segment should match."""
    yaml_names = ["shoulder_pan_joint", "elbow_joint"]
    newton_names = [
        "/World/Robot/Geometry/world/Joints/shoulder_pan_joint",
        "/World/Robot/Geometry/world/Joints/elbow_joint",
    ]
    assert build_dof_index_map(yaml_names, newton_names) == {
        "shoulder_pan_joint": 0,
        "elbow_joint": 1,
    }


def test_reordering_yaml_names_changes_map_order_but_keeps_correct_indices():
    yaml_names = ["c", "a", "b"]
    newton_names = ["a", "b", "c"]
    result = build_dof_index_map(yaml_names, newton_names)
    assert result == {"c": 2, "a": 0, "b": 1}


def test_subset_of_newton_dofs_is_allowed():
    """yaml_names can name fewer DOFs than Newton exposes — extras ignored."""
    yaml_names = ["joint_a"]
    newton_names = ["joint_a", "joint_b", "joint_c"]
    assert build_dof_index_map(yaml_names, newton_names) == {"joint_a": 0}


def test_unmatched_name_raises_runtime_error_with_available_list():
    yaml_names = ["missing_joint"]
    newton_names = ["other_joint_1", "other_joint_2"]
    with pytest.raises(RuntimeError) as excinfo:
        build_dof_index_map(yaml_names, newton_names)
    msg = str(excinfo.value)
    assert "missing_joint" in msg
    # available-names list is included for debugging
    assert "other_joint_1" in msg
    assert "other_joint_2" in msg


def test_empty_yaml_names_returns_empty_map():
    assert build_dof_index_map([], ["a", "b"]) == {}


def test_empty_newton_names_and_empty_yaml_is_ok():
    assert build_dof_index_map([], []) == {}


def test_empty_newton_names_with_yaml_names_raises():
    with pytest.raises(RuntimeError):
        build_dof_index_map(["a"], [])


def test_path_match_only_accepts_last_segment_not_substring():
    """`pan_joint` must not match `/World/shoulder_pan_joint` as a substring —
    only the last `/`-separated segment counts."""
    yaml_names = ["pan_joint"]
    newton_names = ["/World/Robot/shoulder_pan_joint"]
    with pytest.raises(RuntimeError):
        build_dof_index_map(yaml_names, newton_names)


def test_first_match_wins_when_duplicates_present():
    """If Newton somehow reports a name twice, the first occurrence is used."""
    yaml_names = ["j"]
    newton_names = ["j", "j"]
    assert build_dof_index_map(yaml_names, newton_names) == {"j": 0}
