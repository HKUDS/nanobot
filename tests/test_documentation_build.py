"""Documentation stays available across installs and rebuilds."""

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from hatch_build import WebUIBuildHook


def test_editable_install_refreshes_skill_documentation(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    (docs / "guides").mkdir(parents=True)
    (docs / "README.md").write_text("Documentation index", encoding="utf-8")
    guide = docs / "guides" / "setup.md"
    guide.write_text("Setup instructions", encoding="utf-8")
    hook = WebUIBuildHook(
        str(tmp_path), {}, None, {}, "", "wheel",
        SimpleNamespace(display_info=lambda message: None),
    )
    build_data = {}
    hook.initialize("editable", build_data)

    references = tmp_path / "nanobot/skills/nanobot-document/references"
    assert (references / "README.md").read_bytes() == (docs / "README.md").read_bytes()
    assert (references / "guides/setup.md").read_bytes() == guide.read_bytes()

    guide.unlink()
    (docs / "README.md").write_text("Updated index", encoding="utf-8")
    hook.initialize("editable", {})

    assert not (references / "guides/setup.md").exists()
    assert (references / "README.md").read_text(encoding="utf-8") == "Updated index"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory handles")
def test_editable_install_refreshes_docs_with_open_reference_directory(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("Documentation index", encoding="utf-8")
    hook = WebUIBuildHook(
        str(tmp_path), {}, None, {}, "", "wheel",
        SimpleNamespace(display_info=lambda message: None),
    )
    hook.initialize("editable", {})
    references = tmp_path / "nanobot/skills/nanobot-document/references"

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    # Allow file updates while holding the directory against removal, as an
    # editor or file watcher can do while rebuilding an editable install.
    handle = kernel32.CreateFileW(
        ctypes.c_wchar_p(str(references)), 1, 3, None, 3, 0x02000000, None,
    )
    assert handle != ctypes.c_void_p(-1).value, ctypes.WinError(ctypes.get_last_error())
    try:
        (docs / "README.md").write_text("Updated index", encoding="utf-8")
        hook.initialize("editable", {})
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))

    assert (references / "README.md").read_text(encoding="utf-8") == "Updated index"


@pytest.mark.parametrize("ignore_references", [False, True])
def test_wheel_bundles_documentation_once(tmp_path: Path, ignore_references: bool) -> None:
    repository = Path(__file__).resolve().parents[1]
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/README.md").write_text("Documentation index", encoding="utf-8")
    (tmp_path / "nanobot").mkdir()
    (tmp_path / "nanobot/__init__.py").write_text("", encoding="utf-8")
    shutil.copyfile(repository / "nanobot/build_info.py", tmp_path / "nanobot/build_info.py")
    shutil.copyfile(repository / "hatch_build.py", tmp_path / "hatch_build.py")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "documentation-build-test"\nversion = "0.0.0"\n'
        '[tool.hatch.build]\ninclude = ["nanobot/**/*.py", "nanobot/skills/**/*.md"]\n'
        '[tool.hatch.build.hooks.custom]\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["nanobot"]\n',
        encoding="utf-8",
    )
    if ignore_references:
        (tmp_path / ".gitignore").write_text(
            "/nanobot/skills/nanobot-document/references/\n", encoding="utf-8",
        )
    result = subprocess.run(
        [sys.executable, "-c", "import hatchling.build; hatchling.build.build_wheel('dist')"],
        cwd=tmp_path,
        env={**os.environ, "NANOBOT_SKIP_WEBUI_BUILD": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with ZipFile(next((tmp_path / "dist").glob("*.whl"))) as wheel:
        bundled_index = "nanobot/skills/nanobot-document/references/README.md"
        assert wheel.namelist().count(bundled_index) == 1
        assert wheel.read(bundled_index) == b"Documentation index"
