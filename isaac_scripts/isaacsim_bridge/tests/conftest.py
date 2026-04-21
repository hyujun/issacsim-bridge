"""pytest config for host-side unit tests.

Most of isaacsim_bridge/* requires Isaac Sim (pxr, newton, omni, rclpy) and can
only run inside the container. Host-side tests cover the pure-Python logic —
config parsing, DOF name mapping, GUI action dispatch — so they can run in
CI without pulling 20GB of Isaac Sim.

Tests that need the container should be marked `@pytest.mark.container` and
skipped on host; a separate entrypoint runs them via `docker compose exec`.
"""

import sys
from pathlib import Path

import pytest

# Make `isaacsim_bridge` importable without installing the package.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "container: integration test that requires Isaac Sim — skipped on host",
    )
    config.addinivalue_line(
        "markers",
        "phase12: slow Phase 1.2 integration test (boots Isaac Sim container). Opt-in via `-m phase12`.",
    )
    config.addinivalue_line(
        "markers",
        "phase6: slow Phase 6 dual-pack regression gate (boots Isaac Sim container per pack). Opt-in via `-m phase6`.",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip container-marked tests when not inside the Isaac Sim image.

    `phase12` tests run on the host (they drive `docker compose run`), so
    they don't need this gate — but they're slow, so require explicit
    `-m phase12` opt-in (enforced by marker selection in pytest args).
    """
    in_container = Path("/isaac-sim").exists()
    if not in_container:
        skip_marker = pytest.mark.skip(reason="requires Isaac Sim container")
        for item in items:
            if "container" in item.keywords:
                item.add_marker(skip_marker)

    # Auto-skip slow phase-tagged harnesses unless the user explicitly opts in.
    marker_expr = config.getoption("-m") or ""
    for marker in ("phase12", "phase6"):
        if marker not in marker_expr:
            skip = pytest.mark.skip(reason=f"{marker} harness is opt-in; rerun with `-m {marker}`")
            for item in items:
                if marker in item.keywords:
                    item.add_marker(skip)
