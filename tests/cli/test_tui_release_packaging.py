"""Keep shipped corresponding source and runtime materials complete and aligned."""

import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("package_release", ROOT / "tui/scripts/package-release.py")
assert SPEC is not None and SPEC.loader is not None
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


def test_corresponding_source_contains_build_helpers_byte_for_byte():
    root = ROOT / "tui"
    with tarfile.open(fileobj=io.BytesIO(packager._source_archive(root)), mode="r:gz") as archive:
        for relative in (
            "scripts/build.ts",
            "scripts/targets.ts",
            "scripts/target-bindings.ts",
            "scripts/prepare-target.ts",
            "scripts/release-notices.ts",
            "scripts/package-release.py",
        ):
            source = archive.extractfile(f"nanobot-tui-source/tui/{relative}")
            assert source is not None
            assert source.read() == (root / relative).read_bytes(), relative


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
