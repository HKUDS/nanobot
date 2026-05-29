"""Tests for L2 scene index (LM3-A)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.layered_memory.scene.index import SceneEntry, SceneIndex, normalize_slug


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def test_normalize_slug() -> None:
    assert normalize_slug("Layered Memory Dev") == "layered-memory-dev"
    assert normalize_slug("  Git/Commit!!!  ") == "git-commit"
    assert normalize_slug("---") == ""


def test_scene_index_upsert_and_load(workspace: Path) -> None:
    index = SceneIndex(workspace)
    entry = SceneEntry(
        slug="git-workflow",
        title="Git 工作流",
        path="memory/scenes/git-workflow.md",
        session_keys=["cli:direct"],
        updated_at=100.0,
        summary="No auto commit",
        source_atom_ids=["l1_abc"],
    )
    index.upsert(entry)
    loaded = index.load()
    assert len(loaded) == 1
    assert loaded[0].slug == "git-workflow"
    assert loaded[0].session_keys == ["cli:direct"]


def test_scene_index_writes_markdown(workspace: Path) -> None:
    index = SceneIndex(workspace)
    path = index.write_scene_markdown("demo", "# Demo\n\nBody")
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("# Demo")


def test_format_navigation_filters_session(workspace: Path) -> None:
    index = SceneIndex(workspace)
    index.upsert(
        SceneEntry(
            slug="a",
            title="A",
            path="memory/scenes/a.md",
            session_keys=["sess-a"],
            updated_at=2.0,
        )
    )
    index.upsert(
        SceneEntry(
            slug="b",
            title="B",
            path="memory/scenes/b.md",
            session_keys=["sess-b"],
            updated_at=1.0,
        )
    )
    lines = index.format_navigation(session_key="sess-a")
    joined = "\n".join(lines)
    assert "[Scene navigation]" in joined
    assert "A →" in joined
    assert "B →" not in joined


def test_scene_index_persists_json(workspace: Path) -> None:
    index = SceneIndex(workspace)
    index.upsert(
        SceneEntry(
            slug="x",
            title="X",
            path="memory/scenes/x.md",
            updated_at=1.0,
        )
    )
    raw = json.loads(index.index_path.read_text(encoding="utf-8"))
    assert raw["scenes"][0]["slug"] == "x"
