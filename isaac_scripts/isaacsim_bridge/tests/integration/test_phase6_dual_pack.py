"""Phase 6 — agnostic-layer regression gate across every shipped robot pack.

Runs the full launch_sim.py bootstrap in the container once per pack and asserts
the agnostic stack reached `bootstrap complete` with the DOF count from that
pack's robot.yaml. Same entry-point, same USD patches, same ROS bridge — only
$ROBOT_PACK differs between scenarios.

If a new pack is added under robots/, parametrization picks it up automatically
(reads robot.yaml via the agnostic loader). No per-pack code in this file.

Each scenario boots Isaac Sim headless for ~60-90 s. Opt-in:

    pytest -m phase6 -v tests/integration/test_phase6_dual_pack.py
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from isaacsim_bridge import config

pytestmark = pytest.mark.phase6

_REPO_ROOT = Path(__file__).resolve().parents[4]
_RUN_SMOKE = _REPO_ROOT / "isaac_scripts" / "isaacsim_bridge" / "tests" / "integration" / "run_smoke.sh"
_PACKS_DIR = _REPO_ROOT / "robots"

_SUCCESS_LINE = "Newton + ROS2 bridge + robot bootstrap complete"
_SEGFAULT_LINE = re.compile(r"Segmentation fault|Address not mapped")
# Matches the log line emitted by newton_view.setup_newton_articulation.
_DOF_READY = re.compile(r"Newton articulation ready:.*max_dofs=(\d+)\s+yaml_joints=(\d+)")


def _discover_packs() -> list[str]:
    """Return every pack name under robots/ that has a robot.yaml.

    Intentionally filesystem-driven so a new pack needs no test edit.
    """
    if not _PACKS_DIR.is_dir():
        return []
    return sorted(p.name for p in _PACKS_DIR.iterdir() if (p / "robot.yaml").is_file())


def _expected_dof_count(pack_name: str) -> int:
    cfg = config.load_robot_config(_PACKS_DIR / pack_name)
    return len(cfg["joint_names"])


def _run(pack_name: str, max_seconds: int = 60) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as tmp:
        log_path = Path(tmp.name)
    env = os.environ.copy()
    env.update({
        "ROBOT": pack_name,
        "SIM_HEADLESS": "1",
        "SIM_MAX_RUN_SECONDS": str(max_seconds),
    })
    try:
        result = subprocess.run(
            [str(_RUN_SMOKE), str(log_path)],
            env=env,
            capture_output=False,
            timeout=max_seconds + 180,
        )
        return result.returncode, log_path.read_text()
    finally:
        log_path.unlink(missing_ok=True)


@pytest.mark.parametrize("pack_name", _discover_packs())
def test_pack_boots_on_agnostic_stack(pack_name: str):
    """Every pack in robots/ must bootstrap through the unchanged agnostic stack.

    Asserts:
      - `bootstrap complete` log line (agnostic entry-point finished)
      - no segfault
      - Newton articulation's max_dofs equals len(robot.yaml::joint_names)
        — i.e. the runtime assertion in newton_view.setup_newton_articulation
        did not fire.
    """
    expected_dofs = _expected_dof_count(pack_name)
    rc, log = _run(pack_name)

    assert not _SEGFAULT_LINE.search(log), (
        f"{pack_name}: unexpected segfault during bootstrap (rc={rc})"
    )
    assert _SUCCESS_LINE in log, (
        f"{pack_name}: bootstrap did not complete (rc={rc}).\n"
        f"last 30 log lines:\n" + "\n".join(log.splitlines()[-30:])
    )

    match = _DOF_READY.search(log)
    assert match, (
        f"{pack_name}: expected 'Newton articulation ready:' log line not found"
    )
    max_dofs = int(match.group(1))
    yaml_joints = int(match.group(2))
    assert max_dofs == expected_dofs, (
        f"{pack_name}: Newton max_dofs={max_dofs} but robot.yaml joint_names has "
        f"{expected_dofs} entries"
    )
    assert yaml_joints == expected_dofs, (
        f"{pack_name}: log reports yaml_joints={yaml_joints} but robot.yaml has "
        f"{expected_dofs}"
    )
