import sys
from pathlib import Path

# Project root (containing this repo's 'nanobot' package) — inserted FIRST so
# it overrides any other installed 'nanobot' package in the venv.
_NANO1_PKG = Path(__file__).parents[1]   # …/repo_root/
sys.path.insert(0, str(_NANO1_PKG))

# Verify we're using this repo's copy
import nanobot as _nb
print(f"  Using nanobot package from: {Path(_nb.__file__).parents[1]}")

# Now start the web UI server
from webui.server import main  # noqa: E402

main()
