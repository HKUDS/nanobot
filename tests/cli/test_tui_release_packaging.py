"""Keep shipped relinking instructions aligned with the pinned TUI runtime."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("package_release", ROOT / "tui/scripts/package-release.py")
assert SPEC is not None and SPEC.loader is not None
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


def test_current_relinking_matches_pinned_opentui():
    root = ROOT / "tui"
    version = json.loads((root / "package.json").read_text())["dependencies"]["@opentui/core"]
    packager._validate_opentui_version(root, f"===== @opentui/core {version} (MIT) =====")


@pytest.mark.parametrize(
    ("version", "relinking", "notices", "error"),
    [
        ("^0.5.10", "0.5.10", "0.5.10", "exact release version"),
        ("0.5.10", "0.5.3", "0.5.10", "RELINKING.md"),
        ("0.5.10", "0.5.10", "0.5.3", "third-party notices"),
    ],
)
def test_rejects_stale_runtime_materials(tmp_path, version, relinking, notices, error):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"@opentui/core": version}}))
    (tmp_path / "RELINKING.md").write_text(
        f"OpenTUI {relinking}: <https://www.npmjs.com/package/@opentui/core/v/{relinking}>"
    )
    with pytest.raises(ValueError, match=error):
        packager._validate_opentui_version(tmp_path, f"===== @opentui/core {notices} (MIT) =====")
