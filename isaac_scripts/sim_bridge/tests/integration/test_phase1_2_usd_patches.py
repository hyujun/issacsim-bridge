"""Phase 1.2 — per-patch USD-patch validation harness.

For each USD patch in [sim_bridge/usd_patches.py](../../usd_patches.py), run the
full sim bootstrap with that *single* patch suppressed (other 3 still active)
and scan the log for the expected regression signature. If a patch is no
longer needed, its absence won't regress — we remove the patch.

Each scenario boots Isaac Sim in the container (headless, self-closing after
SIM_MAX_RUN_SECONDS). Boot is ~60–90 s each, so these are opt-in: run with

    pytest -m phase12 -v tests/integration/test_phase1_2_usd_patches.py

Results are asserted on log patterns rather than runtime behavior, because
we're characterizing URDFImporter 3.2.1's still-present defects.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.phase12

_REPO_ROOT = Path(__file__).resolve().parents[4]
_RUN_SMOKE = _REPO_ROOT / "isaac_scripts" / "sim_bridge" / "tests" / "integration" / "run_smoke.sh"

# Expected regression signatures — if we skip a patch and see these in the log,
# the patch is still required. Regex applied against the full captured log.
# Keep patterns narrow so we don't false-positive on unrelated Newton noise.
_SIGNATURES = {
    "repair_joint_chain": re.compile(
        r"max_dofs=0|Newton model articulations:.*\[.*,.*,.*\]",  # star topology symptom
    ),
    "strip_zero_mass_api": re.compile(
        r"has zero mass and zero inertia despite having the MassAPI",
    ),
    "populate_robot_schema_links": re.compile(
        r"has links missing from schema relationship",
    ),
    "apply_drive_gains": re.compile(
        r"unresolved target|actuator .* has unresolved",
    ),
}

_SUCCESS_LINE = "Newton + ROS2 bridge + robot bootstrap complete"
_SEGFAULT_LINE = re.compile(r"Segmentation fault|Address not mapped")


def _run(skip: str, robot: str = "ur5e", max_seconds: int = 45) -> tuple[int, str]:
    """Run one smoke scenario and return (exit_code, captured_log_text)."""
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as tmp:
        log_path = Path(tmp.name)
    env = os.environ.copy()
    env.update({
        "ROBOT": robot,
        "SIM_HEADLESS": "1",
        "SIM_SKIP_PATCHES": skip,
        "SIM_MAX_RUN_SECONDS": str(max_seconds),
    })
    try:
        result = subprocess.run(
            [str(_RUN_SMOKE), str(log_path)],
            env=env,
            capture_output=False,
            timeout=max_seconds + 120,  # container boot budget
        )
        return result.returncode, log_path.read_text()
    finally:
        log_path.unlink(missing_ok=True)


# Sanity: with all patches active, bootstrap must complete without segfault.
def test_baseline_all_patches_active():
    rc, log = _run(skip="")
    assert _SUCCESS_LINE in log, f"bootstrap did not complete (rc={rc})"
    assert not _SEGFAULT_LINE.search(log), "unexpected segfault in baseline run"


@pytest.mark.parametrize("patch_name,signature", _SIGNATURES.items())
def test_patch_is_still_required(patch_name: str, signature: re.Pattern[str]):
    """Skip one patch, assert its regression signature appears in logs.

    If the signature is MISSING when we skip the patch → URDFImporter fixed it
    upstream → patch is redundant and should be deleted.
    """
    rc, log = _run(skip=patch_name)
    assert not _SEGFAULT_LINE.search(log), (
        f"skipping {patch_name} caused a segfault — escalate, do not remove"
    )
    found = bool(signature.search(log))
    # Emit structured result for the plan-update step to pick up.
    status = "STILL_REQUIRED" if found else "NO_LONGER_REQUIRED"
    print(f"\n[phase12] patch={patch_name} status={status}")
    # The assertion is SOFT in the sense we record either outcome — only
    # a segfault is a hard fail. Test "passes" either way; the operator
    # reads the status line to decide whether to drop the patch.
