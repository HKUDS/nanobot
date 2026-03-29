from pathlib import Path

from nanobot.coding_tasks.repo_resolver import RepoRefResolver
from nanobot.coding_tasks.router import (
    ParsedCodingTaskRequest,
    detect_coding_task_intent,
    extract_coding_task_slots,
    is_explicit_coding_entry,
    is_start_coding_request,
    parse_start_coding_request,
    resolve_repo_ref,
    validate_repo_path,
)


def test_parse_start_coding_request_with_inline_path_and_goal() -> None:
    parsed = parse_start_coding_request("开始编程 /Users/miau/Documents/demo 修复登录回调")

    assert parsed == ParsedCodingTaskRequest(
        repo_ref="/Users/miau/Documents/demo",
        goal="修复登录回调",
        title=None,
    )


def test_extract_coding_task_slots_with_repo_alias_and_goal() -> None:
    parsed = extract_coding_task_slots("开始编程 codex-remote 的 设置 icon 换一个")

    assert parsed == ParsedCodingTaskRequest(
        repo_ref="codex-remote",
        goal="设置 icon 换一个",
        title=None,
    )


def test_extract_coding_task_slots_with_slash_command_and_repo_alias() -> None:
    parsed = extract_coding_task_slots("/coding codex-remote 的 设置 icon 换一个")

    assert parsed == ParsedCodingTaskRequest(
        repo_ref="codex-remote",
        goal="设置 icon 换一个",
        title=None,
    )


def test_extract_coding_task_slots_with_repo_alias_without_particle() -> None:
    parsed = extract_coding_task_slots("开始编程 codex-remote 底部tab的设置icon换一个")

    assert parsed == ParsedCodingTaskRequest(
        repo_ref="codex-remote",
        goal="底部tab的设置icon换一个",
        title=None,
    )


def test_extract_coding_task_slots_with_structured_fields() -> None:
    parsed = extract_coding_task_slots(
        "开始编程\n仓库: /Users/miau/Documents/demo\n目标: 修复设置页闪退\n标题: 设置页修复"
    )

    assert parsed == ParsedCodingTaskRequest(
        repo_ref="/Users/miau/Documents/demo",
        goal="修复设置页闪退",
        title="设置页修复",
    )


def test_detect_coding_task_intent_requires_explicit_entry() -> None:
    assert detect_coding_task_intent("开始编程 codex-remote 设置 icon 换一个") is True
    assert detect_coding_task_intent("/coding codex-remote 设置 icon 换一个") is True
    assert detect_coding_task_intent("codex-remote 设置 icon 换一个") is False


def test_is_start_coding_request_matches_explicit_prefixes() -> None:
    assert is_start_coding_request("开始编程 /tmp/repo 做点事") is True
    assert is_explicit_coding_entry("/coding codex-remote 的 设置 icon 换一个") is True
    assert is_start_coding_request("帮我看看这个 repo") is False


def test_extract_coding_task_slots_rejects_empty_goal() -> None:
    assert extract_coding_task_slots("开始编程 codex-remote") is None
    assert extract_coding_task_slots("/coding") is None


def test_resolve_repo_ref_rejects_missing_or_file_targets(tmp_path: Path) -> None:
    missing = tmp_path / "missing-repo"
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello", encoding="utf-8")

    resolved, error = resolve_repo_ref(str(missing))
    assert resolved is None
    assert error is not None
    assert "不存在" in error

    resolved, error = resolve_repo_ref(str(file_path))
    assert resolved is None
    assert error is not None
    assert "不是目录" in error


def test_validate_repo_path_accepts_documents_repo_alias(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "Documents" / "codex-remote"
    repo.mkdir(parents=True)

    resolved, error = validate_repo_path("codex-remote")

    assert error is None
    assert resolved == str(repo)


def test_resolve_repo_ref_prefers_alias_table_over_documents_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    alias_repo = tmp_path / "worktrees" / "codex-remote"
    alias_repo.mkdir(parents=True)
    documents_repo = tmp_path / "Documents" / "codex-remote"
    documents_repo.mkdir(parents=True)
    resolver = RepoRefResolver({"codex-remote": str(alias_repo)})

    resolved, error = resolve_repo_ref("codex-remote", repo_resolver=resolver)

    assert error is None
    assert resolved == str(alias_repo)


def test_detect_coding_task_intent_accepts_structured_fields_with_alias_resolver(tmp_path: Path) -> None:
    repo = tmp_path / "repos" / "codex-remote"
    repo.mkdir(parents=True)
    resolver = RepoRefResolver({"codex-remote": str(repo)})

    assert detect_coding_task_intent(
        "开始编程\n仓库: codex-remote\n目标: 设置 icon 换一个",
        repo_resolver=resolver,
    ) is True
