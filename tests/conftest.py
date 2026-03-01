import sys
from pathlib import Path


# Allow running tests without `pip install -e .` by adding repo root to sys.path.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

