import errno
import os
from pathlib import Path

import pytest
import tiktoken

from nanobot.utils import helpers
from nanobot.utils.helpers import (
    _write_text_atomic,
    atomic_write_lines,
    content_with_media_breadcrumbs,
    split_message,
    truncate_text_to_tokens,
)


def test_split_message_no_code_blocks_unchanged():
    content = "alpha beta gamma delta"

    assert split_message(content, max_len=12) == ["alpha beta", "gamma delta"]


def test_split_message_preserves_indentation_after_newline():
    content = "header\n    indented code"

    assert split_message(content, max_len=18) == ["header", "    indented code"]


def test_split_message_preserves_indentation_across_hard_break():
    content = "head\n    abcdefghij"

    assert split_message(content, max_len=8) == ["head", "    abcd", "efghij"]


def test_split_message_preserves_indentation_when_newline_is_at_hard_break():
    content = "abcdefgh\n    code"

    assert split_message(content, max_len=8) == ["abcdefgh", "    code"]
    assert split_message(content.replace("\n", "\r\n"), max_len=8) == [
        "abcdefgh",
        "    code",
    ]


def test_split_message_handles_crlf_before_hard_break():
    content = "header\r\n    indented code"

    assert split_message(content, max_len=18) == ["header", "    indented code"]
    assert split_message("abcdefg\r\n    code", max_len=8) == [
        "abcdefg",
        "    code",
    ]


def test_split_message_preserves_indent_after_space_then_newline_boundary():
    content = "abcdef \n    code"

    assert split_message(content, max_len=7) == ["abcdef", "    cod", "e"]
    assert split_message(content.replace("\n", "\r\n"), max_len=7) == [
        "abcdef",
        "    cod",
        "e",
    ]


def test_split_message_drops_blank_chunks_from_long_indentation():
    content = "head\n" + " " * 20 + "x"

    chunks = split_message(content, max_len=8)

    assert chunks == ["head", "    x"]
    assert all(chunk.strip() for chunk in chunks)


def test_split_message_drops_whitespace_only_line_at_boundary():
    content = "    \nhello world"

    assert split_message(content, max_len=8) == ["hello", "world"]


def test_split_message_drops_whitespace_only_tail_after_hard_break():
    prefix = "abcdefgh"

    assert split_message(prefix + "\n", max_len=8) == [prefix]
    assert split_message(prefix + " ", max_len=8) == [prefix]


def test_split_message_keeps_one_chunk_for_all_whitespace_input():
    content = " " * 10

    assert split_message(content, max_len=4) == [" " * 4]


def test_split_message_nonpositive_maxlen_returns_unsplit():
    content = "alpha beta gamma delta"

    assert split_message(content, max_len=0) == [content]
    assert split_message(content, max_len=-1) == [content]


def test_truncate_text_to_tokens_keeps_text_within_budget():
    text = "hello world " * 100

    result = truncate_text_to_tokens(text, 10_000)

    assert result == text


def test_truncate_text_to_tokens_truncates_over_budget():
    enc = tiktoken.get_encoding("cl100k_base")
    text = "word " * 1_000

    result = truncate_text_to_tokens(text, 50)

    assert result.endswith("\n... (truncated)")
    assert len(enc.encode(result)) <= 50


def test_truncate_text_to_tokens_non_positive_budget_returns_text():
    text = "anything"

    assert truncate_text_to_tokens(text, 0) == text


def test_content_with_media_breadcrumbs_preserves_valid_paths():
    assert content_with_media_breadcrumbs(
        "user",
        "review these",
        ["/media/report.pdf", "/media/clip.mp4"],
    ) == (
        "review these\n"
        "[image: /media/report.pdf]\n"
        "[image: /media/clip.mp4]"
    )


def test_content_with_media_breadcrumbs_only_rewrites_plain_user_content():
    structured = [{"type": "text", "text": "hello"}]

    assert content_with_media_breadcrumbs(
        "assistant",
        "done",
        ["/media/output.png"],
    ) == "done"
    assert content_with_media_breadcrumbs(
        "user",
        structured,
        ["/media/input.png"],
    ) is structured


def test_write_text_atomic_fsyncs_file_and_parent_directory(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "pairing.json"
    fsync_calls: list[int] = []
    closed_fds: list[int] = []

    def fake_fsync(fd: int) -> None:
        fsync_calls.append(fd)

    monkeypatch.setattr(helpers.os, "fsync", fake_fsync)
    monkeypatch.setattr(helpers.os, "open", lambda path, flags: 12345)
    monkeypatch.setattr(helpers.os, "close", lambda fd: closed_fds.append(fd))

    _write_text_atomic(target, '{"approved": {}}')

    assert target.read_text(encoding="utf-8") == '{"approved": {}}'
    assert len(fsync_calls) == 2
    assert fsync_calls[0] != 12345
    assert fsync_calls[1] == 12345
    assert closed_fds == [12345]


def test_write_text_atomic_keeps_file_when_directory_fsync_is_unsupported(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "pairing.json"
    fsync_calls: list[int] = []

    def fake_open(path, flags):
        raise OSError("directory fsync unsupported")

    monkeypatch.setattr(helpers.os, "fsync", lambda fd: fsync_calls.append(fd))
    monkeypatch.setattr(helpers.os, "open", fake_open)

    _write_text_atomic(target, '{"pending": {}}')

    assert target.read_text(encoding="utf-8") == '{"pending": {}}'
    assert len(fsync_calls) == 1


def test_atomic_write_lines_round_trip_replaces_target(tmp_path: Path) -> None:
    """Missing newline insertion or a non-atomic partial write drops records."""
    target = tmp_path / "history.jsonl"
    target.write_text("old\n", encoding="utf-8")

    atomic_write_lines(target, ['{"a": 1}', "café"])

    assert target.read_text(encoding="utf-8") == '{"a": 1}\ncafé\n'
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_lines_empty_input_replaces_file_with_empty(tmp_path: Path) -> None:
    target = tmp_path / "history.jsonl"
    target.write_text("old\n", encoding="utf-8")

    atomic_write_lines(target, [])

    assert target.read_text(encoding="utf-8") == ""
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_lines_cleans_temp_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed replace must not leave a temp file or change the target."""
    target = tmp_path / "history.jsonl"
    target.write_text("kept\n", encoding="utf-8")

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("replace failed")

    monkeypatch.setattr(helpers.os, "replace", fail_replace)

    with pytest.raises(RuntimeError, match="replace failed"):
        atomic_write_lines(target, ["new"])

    assert target.read_text(encoding="utf-8") == "kept\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_lines_cleans_temp_on_base_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KeyboardInterrupt during replace still removes the temp file."""
    target = tmp_path / "history.jsonl"
    target.write_text("kept\n", encoding="utf-8")

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(helpers.os, "replace", interrupt)

    with pytest.raises(KeyboardInterrupt):
        atomic_write_lines(target, ["new"])

    assert target.read_text(encoding="utf-8") == "kept\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_lines_leaves_unrelated_tmp_sibling(tmp_path: Path) -> None:
    """A unique temp name must not clobber a sibling ``*.tmp`` file."""
    target = tmp_path / "history.jsonl"
    stale = target.with_name(target.name + ".tmp")
    stale.write_text("stale", encoding="utf-8")

    atomic_write_lines(target, ["fresh"])

    assert target.read_text(encoding="utf-8") == "fresh\n"
    assert stale.read_text(encoding="utf-8") == "stale"


def test_atomic_write_lines_skips_fsync_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "session.jsonl"
    fsync_calls: list[int] = []
    monkeypatch.setattr(helpers.os, "fsync", lambda fd: fsync_calls.append(fd))

    atomic_write_lines(target, ["line"], fsync=False)

    assert target.read_text(encoding="utf-8") == "line\n"
    assert fsync_calls == []


def test_atomic_write_lines_suppresses_directory_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows directory open raises PermissionError; the replace must still stick."""
    target = tmp_path / "history.jsonl"
    opened: list[tuple[object, int]] = []
    real_open = helpers.os.open

    def open_directory(path: object, flags: int, *args: object, **kwargs: object) -> int:
        opened.append((path, flags))
        if flags == os.O_RDONLY:
            raise PermissionError("directory open denied")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(helpers.os, "open", open_directory)

    atomic_write_lines(target, ["ok"])

    assert target.read_text(encoding="utf-8") == "ok\n"
    assert opened == [(str(tmp_path), os.O_RDONLY)]


def test_atomic_write_lines_suppresses_einval_directory_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EINVAL from the directory fsync is ignored.

    The directory fd is faked so this path runs where ``os.open`` of a directory
    raises ``PermissionError`` (Windows). That suppress path has its own test.
    """
    target = tmp_path / "session.jsonl"
    directory_fd = 12345
    fsync_calls = 0
    real_fsync = helpers.os.fsync
    real_open = helpers.os.open
    real_close = helpers.os.close
    opened: list[tuple[object, int]] = []
    closed: list[int] = []

    def tracking_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if flags == os.O_RDONLY:
            opened.append((path, directory_fd))
            return directory_fd
        return real_open(path, flags, *args, **kwargs)

    def tracking_close(fd: int) -> None:
        closed.append(fd)
        if fd != directory_fd:
            real_close(fd)

    def fsync_then_einval(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            real_fsync(fd)
            return
        raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(helpers.os, "open", tracking_open)
    monkeypatch.setattr(helpers.os, "close", tracking_close)
    monkeypatch.setattr(helpers.os, "fsync", fsync_then_einval)

    atomic_write_lines(target, ["ok"])

    assert target.read_text(encoding="utf-8") == "ok\n"
    assert fsync_calls == 2
    assert opened == [(str(tmp_path), directory_fd)]
    assert closed == [directory_fd]


def test_atomic_write_lines_propagates_other_directory_fsync_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directory fsync errors other than EINVAL propagate.

    The directory fd is faked so this path runs where ``os.open`` of a directory
    raises ``PermissionError`` (Windows). That suppress path has its own test.
    """
    target = tmp_path / "session.jsonl"
    directory_fd = 12345
    fsync_calls = 0
    real_fsync = helpers.os.fsync
    real_open = helpers.os.open
    real_close = helpers.os.close
    opened: list[tuple[object, int]] = []
    closed: list[int] = []

    def tracking_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if flags == os.O_RDONLY:
            opened.append((path, directory_fd))
            return directory_fd
        return real_open(path, flags, *args, **kwargs)

    def tracking_close(fd: int) -> None:
        closed.append(fd)
        if fd != directory_fd:
            real_close(fd)

    def fsync_then_eio(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            real_fsync(fd)
            return
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(helpers.os, "open", tracking_open)
    monkeypatch.setattr(helpers.os, "close", tracking_close)
    monkeypatch.setattr(helpers.os, "fsync", fsync_then_eio)

    with pytest.raises(OSError, match="I/O error"):
        atomic_write_lines(target, ["new"])

    assert target.read_text(encoding="utf-8") == "new\n"
    assert fsync_calls == 2
    assert opened == [(str(tmp_path), directory_fd)]
    assert closed == [directory_fd]
