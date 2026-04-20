"""Host-runnable unit tests for sim_bridge.config.

No Isaac Sim deps — only stdlib + yaml. Exercises pure functions with
in-memory yaml fixtures and on-disk tmp_path packs so tests don't depend
on the real robots/ directory.
"""

from pathlib import Path

import pytest
import yaml

from sim_bridge import config


# ---- load_robot_config ----

def _write_pack(tmp_path: Path, cfg: dict) -> Path:
    pack = tmp_path / "fake_pack"
    pack.mkdir()
    (pack / "robot.yaml").write_text(yaml.safe_dump(cfg))
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
    cfg = {"robot": {"prim_path": "/World/X"}, "joint_names": ["j"]}
    pack = _write_pack(tmp_path, cfg)
    monkeypatch.setenv("ROBOT_PACK", str(pack))
    # Bust the internal cache so prior tests don't leak.
    config._LAZY_CACHE.clear()
    assert config.ROBOT_CFG == cfg


def test_module_level_SIM_CFG_is_lazy(tmp_path, monkeypatch):
    cfg = {"robot": {}, "joint_names": [], "sim": {"mode": "sync"}}
    pack = _write_pack(tmp_path, cfg)
    monkeypatch.setenv("ROBOT_PACK", str(pack))
    config._LAZY_CACHE.clear()
    assert config.SIM_CFG["mode"] == "sync"


def test_module_level_unknown_attr_raises_attribute_error():
    with pytest.raises(AttributeError):
        _ = config.DOES_NOT_EXIST  # noqa: F841
