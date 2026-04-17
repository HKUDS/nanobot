"""Tests for nanobot.agent.skill_store.SkillStore."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.skill_evo.skill_store import SkillStore


_VALID_CONTENT = "---\nname: test-skill\ndescription: A test skill\n---\n\n# Test\n\nDo the thing.\n"


def _make_store(tmp_path: Path) -> tuple[SkillStore, Path]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    store = SkillStore(workspace=workspace, session_key="test-session")
    return store, workspace


# ---------------------------------------------------------------------------
# create_skill
# ---------------------------------------------------------------------------


def test_create_skill_writes_skill_md(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    result = store.create_skill("my-skill", _VALID_CONTENT)
    assert result["success"]
    assert (ws / "skills" / "my-skill" / "SKILL.md").exists()


def test_create_skill_rejects_invalid_name(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    result = store.create_skill("INVALID NAME!", _VALID_CONTENT)
    assert not result["success"]
    assert "Invalid skill name" in result["error"]


def test_create_skill_rejects_empty_name(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    result = store.create_skill("", _VALID_CONTENT)
    assert not result["success"]


def test_create_skill_rejects_long_name(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    result = store.create_skill("a" * 65, _VALID_CONTENT)
    assert not result["success"]
    assert "65" not in result["error"] or "64" in result["error"]


def test_create_skill_rejects_missing_frontmatter(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    result = store.create_skill("no-front", "# No frontmatter\n\nJust body.")
    assert not result["success"]
    assert "frontmatter" in result["error"]


def test_create_skill_rejects_empty_body(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    result = store.create_skill("empty-body", "---\nname: x\ndescription: y\n---\n")
    assert not result["success"]
    assert "empty" in result["error"].lower()


def test_create_skill_rejects_oversized_content(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    huge = "---\nname: big\ndescription: big\n---\n\n" + "x" * 200_000
    result = store.create_skill("big-skill", huge)
    assert not result["success"]
    assert "limit" in result["error"].lower()


def test_create_skill_rejects_duplicate(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    store.create_skill("dup", _VALID_CONTENT)
    result = store.create_skill("dup", _VALID_CONTENT)
    assert not result["success"]
    assert "already exists" in result["error"]


# ---------------------------------------------------------------------------
# edit_skill
# ---------------------------------------------------------------------------


def test_edit_skill_overwrites_content(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    store.create_skill("editable", _VALID_CONTENT)
    new_content = "---\nname: editable\ndescription: Updated\n---\n\n# Updated\n\nNew body.\n"
    result = store.edit_skill("editable", new_content)
    assert result["success"]
    assert "Updated" in (ws / "skills" / "editable" / "SKILL.md").read_text(encoding="utf-8")


def test_edit_skill_clones_builtin(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    builtin = tmp_path / "builtin"
    bi_dir = builtin / "bi-skill"
    bi_dir.mkdir(parents=True)
    (bi_dir / "SKILL.md").write_text(_VALID_CONTENT, encoding="utf-8")

    store = SkillStore(workspace=ws, builtin_skills_dir=builtin)
    new_content = "---\nname: bi-skill\ndescription: Cloned\n---\n\n# Cloned\n\nBody.\n"
    result = store.edit_skill("bi-skill", new_content)
    assert result["success"]
    assert (ws / "skills" / "bi-skill" / "SKILL.md").exists()
    assert "Cloned" in (ws / "skills" / "bi-skill" / "SKILL.md").read_text(encoding="utf-8")


def test_edit_skill_not_found(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    result = store.edit_skill("ghost", _VALID_CONTENT)
    assert not result["success"]
    assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# patch_skill
# ---------------------------------------------------------------------------


def test_patch_skill_unique_match(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    store.create_skill("patchable", _VALID_CONTENT)
    result = store.patch_skill("patchable", "Do the thing.", "Do it better.")
    assert result["success"]
    content = (ws / "skills" / "patchable" / "SKILL.md").read_text(encoding="utf-8")
    assert "Do it better." in content


def test_patch_skill_rejects_multi_match(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    dupe_content = "---\nname: multi\ndescription: multi\n---\n\nfoo bar\nfoo bar\n"
    store.create_skill("multi", dupe_content)
    result = store.patch_skill("multi", "foo bar", "baz")
    assert not result["success"]
    assert "2 times" in result["error"]


def test_patch_skill_replace_all(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    dupe_content = "---\nname: multi\ndescription: multi\n---\n\nfoo bar\nfoo bar\n"
    store.create_skill("multi", dupe_content)
    result = store.patch_skill("multi", "foo bar", "baz", replace_all=True)
    assert result["success"]
    content = (ws / "skills" / "multi" / "SKILL.md").read_text(encoding="utf-8")
    assert "foo bar" not in content


def test_patch_skill_not_found_string(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    store.create_skill("exists", _VALID_CONTENT)
    result = store.patch_skill("exists", "nonexistent string", "replacement")
    assert not result["success"]
    assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# delete_skill
# ---------------------------------------------------------------------------


def test_delete_skill_removes_directory(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    store.create_skill("deletable", _VALID_CONTENT)
    assert (ws / "skills" / "deletable").exists()
    result = store.delete_skill("deletable")
    assert result["success"]
    assert not (ws / "skills" / "deletable").exists()


def test_delete_skill_not_found(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    result = store.delete_skill("ghost")
    assert not result["success"]


# ---------------------------------------------------------------------------
# write_file / remove_file
# ---------------------------------------------------------------------------


def test_write_file_in_allowed_subdir(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    store.create_skill("with-files", _VALID_CONTENT)
    result = store.write_file("with-files", "references/api.md", "# API docs")
    assert result["success"]
    assert (ws / "skills" / "with-files" / "references" / "api.md").exists()


def test_write_file_rejects_disallowed_subdir(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    store.create_skill("blocked", _VALID_CONTENT)
    result = store.write_file("blocked", "secrets/key.pem", "secret data")
    assert not result["success"]


def test_write_file_rejects_traversal(tmp_path: Path) -> None:
    store, _ = _make_store(tmp_path)
    store.create_skill("trav", _VALID_CONTENT)
    result = store.write_file("trav", "references/../../etc/passwd", "hacked")
    assert not result["success"]


def test_remove_file_works(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    store.create_skill("rm-test", _VALID_CONTENT)
    store.write_file("rm-test", "templates/config.yaml", "key: value")
    result = store.remove_file("rm-test", "templates/config.yaml")
    assert result["success"]
    assert not (ws / "skills" / "rm-test" / "templates" / "config.yaml").exists()


# ---------------------------------------------------------------------------
# Manifest & audit log
# ---------------------------------------------------------------------------


def test_manifest_updated_after_create(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    store.create_skill("tracked", _VALID_CONTENT)
    manifest = json.loads((ws / "skills" / ".skill-manifest.json").read_text(encoding="utf-8"))
    assert "tracked" in manifest
    assert manifest["tracked"]["created_by"] == "test-session"


def test_manifest_cleared_after_delete(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    store.create_skill("tracked", _VALID_CONTENT)
    store.delete_skill("tracked")
    manifest = json.loads((ws / "skills" / ".skill-manifest.json").read_text(encoding="utf-8"))
    assert "tracked" not in manifest


def test_events_log_appended(tmp_path: Path) -> None:
    store, ws = _make_store(tmp_path)
    store.create_skill("logged", _VALID_CONTENT)
    store.patch_skill("logged", "Do the thing.", "Did it.")
    events_path = ws / "skills" / ".skill-events.jsonl"
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    ev1 = json.loads(lines[0])
    assert ev1["action"] == "create"
    assert ev1["skill_name"] == "logged"
    ev2 = json.loads(lines[1])
    assert ev2["action"] == "patch"
