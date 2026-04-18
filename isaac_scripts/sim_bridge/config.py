"""Robot pack + robot.yaml loader.

Safe to import before SimulationApp is up — only stdlib + yaml.
"""

import os
from pathlib import Path

import yaml

ROBOT_PACK = Path(os.environ.get("ROBOT_PACK", "/workspace/robots/ur5e"))
ROBOT_CFG_PATH = ROBOT_PACK / "robot.yaml"

with ROBOT_CFG_PATH.open() as fh:
    ROBOT_CFG = yaml.safe_load(fh)
