from pathlib import Path

from nanobot.security.workspace_access import default_workspace_scope
from nanobot.webui.path_evidence import (
    MAX_EVIDENCE_MESSAGES,
    extract_path_evidence,
    resolve_with_evidence,
)


def _tool_call(name: str, path: str) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": f"call_{name}_{len(path)}",
                "type": "function",
                "function": {"name": name, "arguments": f'{{"path": "{path}"}}'},
            }
        ],
    }


def test_extract_evidence_from_read_file_parent_dir(tmp_path: Path) -> None:
    messages = [
        _tool_call("read_file", f"{tmp_path}/a/b/file.md"),
        _tool_call("list_dir", f"{tmp_path}/a"),
    ]
    evidence = extract_path_evidence(messages)

    # list_dir contributes its own dir; read_file contributes its parent,
    # grandparent, great-grandparent (3 levels). Most recent (last message)
    # comes first.
    assert evidence[0] == Path(f"{tmp_path}/a")
    assert Path(f"{tmp_path}/a/b") in evidence
    assert Path(f"{tmp_path}/a") in evidence
    assert tmp_path in evidence


def test_extract_evidence_ignores_exec_and_relative_paths(tmp_path: Path) -> None:
    messages = [
        _tool_call("exec", "cd /tmp && ls"),
        _tool_call("read_file", "relative/path/file.md"),
    ]
    assert extract_path_evidence(messages) == []


def test_extract_evidence_limits_recent_messages(tmp_path: Path) -> None:
    messages = [_tool_call("read_file", f"{tmp_path}/recent/sub/recent.md")]
    old = [
        {"role": "assistant", "content": "", "tool_calls": []}
        for _ in range(MAX_EVIDENCE_MESSAGES)
    ]
    old[0] = _tool_call("read_file", f"{tmp_path}/old/very-old.md")
    evidence = extract_path_evidence(old + messages)

    assert Path(f"{tmp_path}/recent/sub/recent.md").parent in evidence
    assert Path(f"{tmp_path}/recent/sub") in evidence
    assert Path(f"{tmp_path}/old/very-old.md").parent not in evidence
    assert Path(f"{tmp_path}/old") not in evidence


def test_resolve_with_evidence_hits_cross_directory_file(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    other = tmp_path / "other-repo"
    docs = other / "分析报告"
    docs.mkdir(parents=True)
    target = docs / "报告.md"
    target.write_text("正文", encoding="utf-8")

    scope = default_workspace_scope(workspace, restrict_to_workspace=False)
    evidence = [docs]

    resolved = resolve_with_evidence("报告.md", evidence, scope=scope)
    assert resolved == target.resolve()


def test_resolve_with_evidence_skips_boundary_violations(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("secret", encoding="utf-8")

    scope = default_workspace_scope(workspace, restrict_to_workspace=True)
    # Evidence dir is outside the workspace: must not resolve in restricted mode.
    assert resolve_with_evidence("secret.md", [outside], scope=scope) is None

    # Full access may resolve it (restricted boundary is the only guard).
    full_scope = default_workspace_scope(workspace, restrict_to_workspace=False)
    assert resolve_with_evidence("secret.md", [outside], scope=full_scope) == secret.resolve()


def test_resolve_with_evidence_returns_none_when_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()

    scope = default_workspace_scope(workspace, restrict_to_workspace=False)
    assert resolve_with_evidence("nope.md", [docs], scope=scope) is None


def test_resolve_with_evidence_prefers_most_recent_dir(tmp_path: Path) -> None:
    """Same file name in two evidence dirs: most recent (first) wins."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "same.md").write_text("A", encoding="utf-8")
    (dir_b / "same.md").write_text("B", encoding="utf-8")

    scope = default_workspace_scope(workspace, restrict_to_workspace=False)
    assert resolve_with_evidence("same.md", [dir_a, dir_b], scope=scope) == (dir_a / "same.md").resolve()
    assert resolve_with_evidence("same.md", [dir_b, dir_a], scope=scope) == (dir_b / "same.md").resolve()
