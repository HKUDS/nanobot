"""Documentation stays available across installs and rebuilds."""

from pathlib import Path
from types import SimpleNamespace

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
