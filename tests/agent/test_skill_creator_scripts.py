import importlib
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path("janniebot/skills/skill-creator/scripts").resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

init_skill = importlib.import_module("init_skill")
package_skill = importlib.import_module("package_skill")
quick_validate = importlib.import_module("quick_validate")


def test_init_skill_creates_expected_files(tmp_path: Path) -> None:
    skill_dir = init_skill.init_skill(
        "demo-skill",
        tmp_path,
        ["scripts", "references", "assets"],
        include_examples=True,
    )

    assert skill_dir == tmp_path / "demo-skill"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "scripts" / "example.py").exists()
    assert (skill_dir / "references" / "api_reference.md").exists()
    assert (skill_dir / "assets" / "example_asset.txt").exists()


def test_validate_skill_accepts_existing_skill_creator() -> None:
    valid, message = quick_validate.validate_skill(
        Path("janniebot/skills/skill-creator").resolve()
    )

    assert valid, message


def test_validate_skill_rejects_placeholder_description(tmp_path: Path) -> None:
    skill_dir = tmp_path / "placeholder-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: placeholder-skill\n"
        'description: "[TODO: fill me in]"\n'
        "---\n"
        "# Placeholder\n",
        encoding="utf-8",
    )

    valid, message = quick_validate.validate_skill(skill_dir)

    assert not valid
    assert "TODO placeholder" in message


def test_validate_skill_rejects_root_files_outside_allowed_dirs(tmp_path: Path) -> None:
    skill_dir = tmp_path / "bad-root-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: bad-root-skill\n"
        "description: Valid description\n"
        "---\n"
        "# Skill\n",
        encoding="utf-8",
    )
    (skill_dir / "README.md").write_text("extra\n", encoding="utf-8")

    valid, message = quick_validate.validate_skill(skill_dir)

    assert not valid
    assert "Unexpected file or directory in skill root" in message


def test_package_skill_creates_archive(tmp_path: Path) -> None:
    skill_dir = tmp_path / "package-me"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: package-me\n"
        "description: Package this skill.\n"
        "---\n"
        "# Skill\n",
        encoding="utf-8",
    )
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "helper.py").write_text("print('ok')\n", encoding="utf-8")

    archive_path = package_skill.package_skill(skill_dir, tmp_path / "dist")

    assert archive_path == (tmp_path / "dist" / "package-me.skill")
    assert archive_path.exists()
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = set(archive.namelist())
    assert "package-me/SKILL.md" in names
    assert "package-me/scripts/helper.py" in names


def test_package_skill_rejects_symlink(tmp_path: Path) -> None:
    skill_dir = tmp_path / "symlink-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: symlink-skill\n"
        "description: Reject symlinks during packaging.\n"
        "---\n"
        "# Skill\n",
        encoding="utf-8",
    )
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("secret\n", encoding="utf-8")
    link = scripts_dir / "outside.txt"

    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return

    archive_path = package_skill.package_skill(skill_dir, tmp_path / "dist")

    assert archive_path is None
    assert not (tmp_path / "dist" / "symlink-skill.skill").exists()
