"""Host-runnable unit tests for isaacsim_bridge.config.

No Isaac Sim deps — only stdlib + yaml. Exercises pure functions with
in-memory yaml fixtures and on-disk tmp_path packs so tests don't depend
on the real robots/ directory.
"""

from pathlib import Path

import pytest
import yaml

from isaacsim_bridge import config


# ---- load_robot_config ----

def _write_pack(tmp_path: Path, cfg: dict) -> Path:
    pack = tmp_path / "fake_pack"
    pack.mkdir()
    (pack / "robot.yaml").write_text(yaml.safe_dump(cfg))
    return pack


def _valid_cfg(**overrides) -> dict:
    """Minimal robot.yaml dict that passes validate_robot_config.

    Tests that specifically exercise validation override fields to break it.
    Tests of unrelated behavior use this as a baseline so adding new required
    fields doesn't ripple across unrelated tests.
    """
    base = {
        "robot": {
            "urdf_rel": "urdf/fake.urdf",
            "usd_rel": "usd/fake/fake.usda",
            "prim_path": "/World/Robot",
            "root_link": "base_link",
        },
        "joint_names": ["j1"],
        "drive": {"mode": "position", "stiffness": 100.0, "damping": 10.0},
        "ros": {"joint_states_topic": "/joint_states", "joint_command_topic": "/joint_command"},
    }
    base.update(overrides)
    return base


def _write_valid_pack(tmp_path: Path, **overrides) -> Path:
    """Like _write_pack but also creates the urdf_rel file so on-disk check passes."""
    cfg = _valid_cfg(**overrides)
    pack = _write_pack(tmp_path, cfg)
    urdf = pack / cfg["robot"]["urdf_rel"]
    urdf.parent.mkdir(parents=True, exist_ok=True)
    urdf.write_text("<robot/>")
    return pack


def test_load_robot_config_returns_parsed_yaml(tmp_path):
    cfg = {"robot": {"prim_path": "/World/Robot"}, "joint_names": ["a", "b"]}
    pack = _write_pack(tmp_path, cfg)
    assert config.load_robot_config(pack) == cfg


def test_load_robot_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        config.load_robot_config(tmp_path / "nonexistent")


# ---- compute_sim_config ----

def test_compute_sim_config_applies_defaults_when_no_sim_section():
    """Legacy robot.yaml without sim: falls back to freerun + legacy dt."""
    sim = config.compute_sim_config({})
    assert sim["mode"] == "freerun"
    assert sim["substeps"] == 4
    assert sim["render_rate_hz"] == 60
    assert sim["step_rate_hz"] == 500
    assert sim["sync_timeout_s"] == 0.5


def test_compute_sim_config_user_values_override_defaults():
    sim = config.compute_sim_config({
        "sim": {"mode": "sync", "step_rate_hz": 1000, "substeps": 2}
    })
    assert sim["mode"] == "sync"
    assert sim["step_rate_hz"] == 1000
    assert sim["substeps"] == 2
    # Unspecified fields keep defaults.
    assert sim["render_rate_hz"] == 60


def test_compute_sim_config_partial_override_preserves_unspecified():
    sim = config.compute_sim_config({"sim": {"render_rate_hz": 30}})
    assert sim["render_rate_hz"] == 30
    assert sim["mode"] == "freerun"  # default preserved


def test_compute_sim_config_rejects_unknown_mode():
    with pytest.raises(ValueError, match="sim.mode"):
        config.compute_sim_config({"sim": {"mode": "invalid"}})


def test_compute_sim_config_null_sim_section_is_treated_as_empty():
    """`sim:` with no body yields None from yaml — must not crash."""
    sim = config.compute_sim_config({"sim": None})
    assert sim["mode"] == "freerun"


# ---- default_pack_path / lazy module-level access ----

def test_default_pack_path_honors_env(monkeypatch):
    monkeypatch.setenv("ROBOT_PACK", "/tmp/custom/pack")
    assert config.default_pack_path() == Path("/tmp/custom/pack")


def test_default_pack_path_falls_back_when_env_unset(monkeypatch):
    monkeypatch.delenv("ROBOT_PACK", raising=False)
    assert config.default_pack_path() == Path("/workspace/robots/ur5e")


def test_module_level_ROBOT_CFG_is_lazy(tmp_path, monkeypatch):
    """Accessing config.ROBOT_CFG loads yaml from ROBOT_PACK on demand."""
    pack = _write_valid_pack(tmp_path)
    monkeypatch.setenv("ROBOT_PACK", str(pack))
    # Bust the internal cache so prior tests don't leak.
    config._LAZY_CACHE.clear()
    assert config.ROBOT_CFG["robot"]["prim_path"] == "/World/Robot"


def test_module_level_SIM_CFG_is_lazy(tmp_path, monkeypatch):
    pack = _write_valid_pack(tmp_path, sim={"mode": "sync"})
    monkeypatch.setenv("ROBOT_PACK", str(pack))
    config._LAZY_CACHE.clear()
    assert config.SIM_CFG["mode"] == "sync"


def test_module_level_ROBOT_CFG_raises_on_invalid_pack(tmp_path, monkeypatch):
    """Lazy access runs validation so launch_sim.py fails fast with a clear error."""
    pack = _write_pack(tmp_path, {"robot": {"prim_path": "/World/Robot"}})  # missing most fields
    monkeypatch.setenv("ROBOT_PACK", str(pack))
    config._LAZY_CACHE.clear()
    with pytest.raises(ValueError, match="robot.yaml validation failed"):
        _ = config.ROBOT_CFG


def test_module_level_unknown_attr_raises_attribute_error():
    with pytest.raises(AttributeError):
        _ = config.DOES_NOT_EXIST  # noqa: F841


# ---- validate_robot_config ----

def test_validate_accepts_minimal_valid_cfg():
    config.validate_robot_config(_valid_cfg())


def test_validate_reports_all_missing_fields_at_once():
    """Caller sees every problem, not just the first KeyError."""
    with pytest.raises(ValueError) as exc:
        config.validate_robot_config({})
    msg = str(exc.value)
    assert "robot.urdf_rel" in msg
    assert "robot.usd_rel" in msg
    assert "robot.prim_path" in msg
    assert "robot.root_link" in msg
    assert "joint_names" in msg
    assert "drive.stiffness" in msg
    assert "ros.joint_states_topic" in msg


def test_validate_rejects_empty_joint_names():
    cfg = _valid_cfg()
    cfg["joint_names"] = []
    with pytest.raises(ValueError, match="joint_names must be a non-empty list"):
        config.validate_robot_config(cfg)


def test_validate_rejects_non_list_joint_names():
    cfg = _valid_cfg()
    cfg["joint_names"] = "not_a_list"
    with pytest.raises(ValueError, match="joint_names must be a non-empty list"):
        config.validate_robot_config(cfg)


def test_validate_rejects_unknown_drive_mode():
    cfg = _valid_cfg()
    cfg["drive"]["mode"] = "velocity"
    with pytest.raises(ValueError, match="drive.mode must be 'position'"):
        config.validate_robot_config(cfg)


def test_validate_checks_urdf_exists_when_pack_path_given(tmp_path):
    pack = _write_valid_pack(tmp_path)
    (pack / "urdf" / "fake.urdf").unlink()  # remove the file the helper created
    with pytest.raises(ValueError, match="robot.urdf_rel not found"):
        config.validate_robot_config(_valid_cfg(), pack)


def test_validate_skips_on_disk_checks_when_pack_path_none():
    """Unit tests with synthetic cfg shouldn't need to fake a urdf file."""
    config.validate_robot_config(_valid_cfg(), pack_path=None)


def test_validate_passes_real_ur5e_pack():
    """Guard the packs we ship — validation must accept them as-is."""
    ur5e = Path(__file__).resolve().parents[3] / "robots" / "ur5e"
    if not (ur5e / "robot.yaml").exists():
        pytest.skip(f"ur5e pack not present at {ur5e}")
    cfg = config.load_robot_config(ur5e)
    config.validate_robot_config(cfg, ur5e)


def test_validate_passes_real_robotiq_2f_85_pack():
    pack = Path(__file__).resolve().parents[3] / "robots" / "robotiq_2f_85"
    if not (pack / "robot.yaml").exists():
        pytest.skip(f"robotiq_2f_85 pack not present at {pack}")
    cfg = config.load_robot_config(pack)
    config.validate_robot_config(cfg, pack)
