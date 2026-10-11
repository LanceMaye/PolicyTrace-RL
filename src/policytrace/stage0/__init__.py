"""CPU-only compatibility layer. Contains no training or agent harness."""
import os
from pathlib import Path

# This is the upstream assets directory, NOT the AReaL snapshot directory.
os.environ.setdefault("TAU2_DATA_DIR", str(Path(__file__).resolve().parents[3] / "external/tau2-bench/data"))
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

