"""Convert Robotiq 2F-85 URDF -> USD using Isaac Sim's URDF importer.

URDF source: ros-jazzy-robotiq-description (xacro expanded host-side in
build_urdf.sh). Re-run only when the URDF changes.

Run inside the container:
  ROBOT=robotiq_2f_85 ./run.sh convert
"""

from pathlib import Path

from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": True})

from isaacsim.core.utils.extensions import enable_extension

enable_extension("isaacsim.asset.importer.urdf")
simulation_app.update()

from isaacsim.asset.importer.urdf import URDFImporter, URDFImporterConfig

PACK_DIR = Path(__file__).resolve().parent
URDF_PATH = str(PACK_DIR / "urdf" / "robotiq_2f_85.urdf")
USD_OUT = str(PACK_DIR / "usd")

config = URDFImporterConfig()
config.urdf_path = URDF_PATH
config.usd_path = USD_OUT
config.allow_self_collision = False
config.collision_from_visuals = False
config.merge_mesh = False

importer = URDFImporter()
importer.config = config
result = importer.import_urdf()

print(f"[convert_urdf] imported -> {USD_OUT} (result={result!r})")
