from nanobot.coding_tasks.router import (
    ParsedCodingTaskRequest,
    is_start_coding_request,
    parse_start_coding_request,
    validate_repo_path,
)


def test_parse_start_coding_request_with_inline_path_and_goal() -> None:
    parsed = parse_start_coding_request("开始编程 /Users/miau/Documents/demo 修复登录回调")

    assert parsed == ParsedCodingTaskRequest(
        repo_path="/Users/miau/Documents/demo",
        goal="修复登录回调",
        title=None,
    )


def test_parse_start_coding_request_with_repo_alias_and_goal() -> None:
    parsed = parse_start_coding_request("开始编程 codex-remote 的 设置 icon 换一个")

    assert parsed == ParsedCodingTaskRequest(
        repo_path="codex-remote",
        goal="设置 icon 换一个",
        title=None,
    )


def test_parse_start_coding_request_with_slash_command_and_repo_alias() -> None:
    parsed = parse_start_coding_request("/coding codex-remote 的 设置 icon 换一个")

    assert parsed == ParsedCodingTaskRequest(
        repo_path="codex-remote",
        goal="设置 icon 换一个",
        title=None,
    )


def test_parse_start_coding_request_with_structured_fields() -> None:
    parsed = parse_start_coding_request(
        "开始编程\n仓库: /Users/miau/Documents/demo\n目标: 修复设置页闪退\n标题: 设置页修复"
    )

    assert parsed == ParsedCodingTaskRequest(
        repo_path="/Users/miau/Documents/demo",
        goal="修复设置页闪退",
        title="设置页修复",
    )


def test_is_start_coding_request_matches_only_expected_prefix() -> None:
    assert is_start_coding_request("开始编程 /tmp/repo 做点事") is True
    assert is_start_coding_request("/coding codex-remote 的 设置 icon 换一个") is True
    assert is_start_coding_request("帮我看看这个 repo") is False


def test_validate_repo_path_rejects_missing_or_file_targets(tmp_path) -> None:
    missing = tmp_path / "missing-repo"
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello", encoding="utf-8")

    resolved, error = validate_repo_path(str(missing))
    assert resolved is None
    assert error is not None
    assert "不存在" in error

    resolved, error = validate_repo_path(str(file_path))
    assert resolved is None
    assert error is not None
    assert "不是目录" in error


def test_validate_repo_path_accepts_documents_repo_alias(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "Documents" / "codex-remote"
    repo.mkdir(parents=True)

    resolved, error = validate_repo_path("codex-remote")

    assert error is None
    assert resolved == str(repo)
