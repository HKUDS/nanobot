import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.security.workspace_access import default_workspace_scope
from nanobot.webui.file_preview import (
    WebUIFilePreviewError,
    file_preview_availability_payload,
    file_preview_payload,
)
from nanobot.webui.ws_http import GatewayHTTPHandler


def test_restricted_preview_allows_media_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    uploaded = media / "upload.txt"
    uploaded.write_text("uploaded", encoding="utf-8")
    monkeypatch.setattr("nanobot.webui.file_preview.get_media_dir", lambda: media)

    scope = default_workspace_scope(workspace, restrict_to_workspace=True)

    payload = file_preview_payload(str(uploaded), scope=scope)

    assert payload["content"] == "uploaded"
    assert Path(payload["path"]) == uploaded.resolve()


def test_restricted_preview_rejects_other_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr("nanobot.webui.file_preview.get_media_dir", lambda: media)

    scope = default_workspace_scope(workspace, restrict_to_workspace=True)

    with pytest.raises(WebUIFilePreviewError, match="outside the current workspace") as exc_info:
        file_preview_payload(str(outside), scope=scope)

    assert exc_info.value.status == 403


def _prefixed_project(tmp_path: Path) -> tuple[Path, Path]:
    """Create a project directory whose name also appears in relative refs."""
    project = tmp_path / "qizicheng-skill管理删除优化"
    docs = project / "01_docs" / "03_方案"
    docs.mkdir(parents=True)
    doc = docs / "Skill删除优化-替换文件方案-v1.0.md"
    doc.write_text("# 方案\n\n正文内容", encoding="utf-8")
    return project, doc


def test_prefixed_project_name_reference_is_available(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    raw = f"{project.name}/01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md"

    assert file_preview_availability_payload(raw, scope=scope) == {"available": True}


def test_prefixed_project_name_reference_resolves_payload(tmp_path: Path) -> None:
    project, doc = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    raw = f"{project.name}/01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md"
    payload = file_preview_payload(raw, scope=scope)

    assert Path(payload["path"]) == doc.resolve()
    assert payload["display_path"] == "01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md"
    assert payload["content"] == "# 方案\n\n正文内容"


def test_relative_reference_without_prefix_resolves_directly(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    assert file_preview_availability_payload(
        "01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md",
        scope=scope,
    ) == {"available": True}


def test_absolute_reference_resolves_directly(tmp_path: Path) -> None:
    project, doc = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    assert file_preview_availability_payload(str(doc), scope=scope) == {"available": True}


def test_missing_file_still_404(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    with pytest.raises(WebUIFilePreviewError, match="file not found") as exc_info:
        file_preview_availability_payload(
            "01_docs/03_方案/不存在的文件.md",
            scope=scope,
        )

    assert exc_info.value.status == 404


def test_prefixed_missing_file_still_404_after_retry(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    raw = f"{project.name}/01_docs/03_方案/不存在的文件.md"
    with pytest.raises(WebUIFilePreviewError, match="file not found") as exc_info:
        file_preview_availability_payload(raw, scope=scope)

    assert exc_info.value.status == 404


def test_unrelated_prefix_still_404(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    raw = "other-project/01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md"
    with pytest.raises(WebUIFilePreviewError, match="file not found") as exc_info:
        file_preview_availability_payload(raw, scope=scope)

    assert exc_info.value.status == 404


def test_evidence_fallback_resolves_cross_repo_reference(tmp_path: Path) -> None:
    """A relative path that misses the project root resolves via tool evidence."""
    project = tmp_path / "13_nanobot"  # session project root (production repo)
    project.mkdir()
    dev_repo = tmp_path / "13_nanobot-dev"  # where the agent actually worked
    docs = dev_repo / "分析报告"
    docs.mkdir(parents=True)
    doc = docs / "报告.md"
    doc.write_text("跨库正文", encoding="utf-8")

    scope = default_workspace_scope(project, restrict_to_workspace=False)
    # Evidence mirrors extract_path_evidence output: the agent's read_file
    # touched .../13_nanobot-dev/分析报告/报告.md, whose ancestor bases are
    # [分析报告, 13_nanobot-dev, tmp_path] (newest first). The reference base
    # is 13_nanobot-dev, so 分析报告/报告.md resolves via the ancestor entry.
    evidence = [docs, dev_repo]

    assert file_preview_availability_payload(
        "分析报告/报告.md", scope=scope, evidence_provider=lambda: evidence
    ) == {"available": True}

    payload = file_preview_payload(
        "分析报告/报告.md", scope=scope, evidence_provider=lambda: evidence
    )
    assert payload["content"] == "跨库正文"
    assert Path(payload["path"]) == doc.resolve()


def test_evidence_fallback_ignored_when_project_root_hits(tmp_path: Path) -> None:
    """Baseline-aligned references keep resolving via project root (zero change)."""
    project, doc = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    # Evidence points somewhere else entirely; it must not shadow the direct hit.
    stray = tmp_path / "stray"
    stray.mkdir()

    assert file_preview_availability_payload(
        "01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md",
        scope=scope,
        evidence_provider=lambda: [stray],
    ) == {"available": True}

    payload = file_preview_payload(
        "01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md",
        scope=scope,
        evidence_provider=lambda: [stray],
    )
    assert Path(payload["path"]) == doc.resolve()


def test_evidence_fallback_prefers_most_recent_dir_on_duplicate(tmp_path: Path) -> None:
    """Same relative name in two evidence dirs: most-recent base wins, never guessed."""
    project = tmp_path / "project"
    project.mkdir()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "dup.md").write_text("A", encoding="utf-8")
    (dir_b / "dup.md").write_text("B", encoding="utf-8")

    scope = default_workspace_scope(project, restrict_to_workspace=False)

    # dir_a is the most recently touched base (evidence order is newest first).
    payload = file_preview_payload(
        "dup.md", scope=scope, evidence_provider=lambda: [dir_a, dir_b]
    )
    assert payload["content"] == "A"

    payload = file_preview_payload(
        "dup.md", scope=scope, evidence_provider=lambda: [dir_b, dir_a]
    )
    assert payload["content"] == "B"


def test_evidence_fallback_respects_restricted_boundary(tmp_path: Path) -> None:
    """Evidence pointing outside the workspace must not bypass restricted mode."""
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("secret", encoding="utf-8")

    scope = default_workspace_scope(project, restrict_to_workspace=True)

    with pytest.raises(WebUIFilePreviewError, match="file not found") as exc_info:
        file_preview_availability_payload(
            "secret.md", scope=scope, evidence_provider=lambda: [outside]
        )
    assert exc_info.value.status == 404


# -- Handler-level integration: session evidence injected via ws_http --------


def _preview_handler(
    *,
    session_data: dict | None,
    scope,
    authorized: bool = True,
) -> GatewayHTTPHandler:
    handler = object.__new__(GatewayHTTPHandler)
    handler.tokens = SimpleNamespace(check_api_token=lambda _request: authorized)
    handler.session_manager = SimpleNamespace(
        read_session_file=lambda _key: session_data,
    )
    handler.workspaces = SimpleNamespace(scope_for_session_key=lambda _key: scope)
    return handler


def _preview_request(path: str) -> SimpleNamespace:
    return SimpleNamespace(path=path, headers=SimpleNamespace())


def _preview_response_json(response) -> dict:
    body = getattr(response, "body", None)
    if body is None:
        return {}
    return json.loads(body.decode("utf-8"))


def test_handler_uses_session_evidence_for_cross_repo_probe(tmp_path: Path) -> None:
    """End-to-end: session tool activity lets a cross-repo relative path probe true."""
    project = tmp_path / "13_nanobot"  # session project root
    project.mkdir()
    dev_repo = tmp_path / "13_nanobot-dev"  # where the agent actually worked
    docs = dev_repo / "分析报告"
    docs.mkdir(parents=True)
    doc = docs / "报告.md"
    doc.write_text("跨库正文", encoding="utf-8")

    # Session transcript: the agent read the file in the dev repo.
    session_data = {
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": str(doc)}),
                        },
                    }
                ],
            }
        ]
    }

    scope = default_workspace_scope(project, restrict_to_workspace=False)
    handler = _preview_handler(session_data=session_data, scope=scope)

    response = handler._handle_file_preview(
        _preview_request("/api/sessions/k/file-preview?path=分析报告/报告.md&probe=1"),
        "websocket:key",
    )

    assert _preview_response_json(response) == {"available": True}


def test_handler_evidence_respects_restricted_scope(tmp_path: Path) -> None:
    """Handler-level: evidence outside a restricted workspace stays unavailable."""
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("secret", encoding="utf-8")

    session_data = {
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": str(secret)}),
                        },
                    }
                ],
            }
        ]
    }

    scope = default_workspace_scope(project, restrict_to_workspace=True)
    handler = _preview_handler(session_data=session_data, scope=scope)

    response = handler._handle_file_preview(
        _preview_request("/api/sessions/k/file-preview?path=secret.md&probe=1"),
        "websocket:key",
    )

    payload = _preview_response_json(response)
    assert payload["available"] is False
    assert payload["reason"] == "not_found"
    assert payload["requested"] == "secret.md"
