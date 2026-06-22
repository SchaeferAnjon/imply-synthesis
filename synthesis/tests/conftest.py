"""Test path setup: make synthesis/ and ../ (imply_sim.py) importable."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent       # synthesis/
for _p in (str(ROOT), str(ROOT.parent)):            # parent holds imply_sim.py
    if _p not in sys.path:
        sys.path.insert(0, _p)


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers", "slow: exhaustive verification of the larger circuits")
