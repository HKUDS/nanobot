"""Tests for nanobot.security.protected_paths — filesystem-level write guard."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.security.protected_paths import (
    PROTECTED_FILES,
    harden,
    is_hardened,
    is_protected,
    writable,
)

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def test_protected_manifest_covers_memory_store_artefacts():
    assert "history.jsonl" in PROTECTED_FILES
    assert ".dream_cursor" in PROTECTED_FILES


@pytest.mark.parametrize("name", ["history.jsonl", ".dream_cursor"])
def test_is_protected_matches_basename(name: str, tmp_path: Path):
    assert is_protected(tmp_path / name)
    assert is_protected(name)


@pytest.mark.parametrize("name", ["MEMORY.md", "history.json", "dream_cursor", ".cursor"])
def test_is_protected_rejects_lookalikes(name: str, tmp_path: Path):
    assert not is_protected(tmp_path / name)


# ---------------------------------------------------------------------------
# harden() — sets 0o444 when file exists, tolerates when it does not
# ---------------------------------------------------------------------------

def test_harden_sets_readonly_mode(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    p.write_text("content", encoding="utf-8")
    harden(p)
    assert is_hardened(p)


def test_is_hardened_false_for_writable_file(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    p.write_text("x", encoding="utf-8")
    # default mode is writable
    assert not is_hardened(p)


def test_is_hardened_false_for_missing_file(tmp_path: Path):
    assert not is_hardened(tmp_path / "absent.jsonl")


def test_harden_missing_file_is_noop(tmp_path: Path):
    p = tmp_path / "absent.jsonl"
    # Must not raise
    harden(p)
    assert not p.exists()


def test_harden_swallows_chmod_errors(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    p.write_text("x", encoding="utf-8")
    with patch("nanobot.security.protected_paths.os.chmod", side_effect=OSError("ro fs")):
        # Must not raise even though chmod failed
        harden(p)


# ---------------------------------------------------------------------------
# writable() — briefly unhardens, restores even on exception
# ---------------------------------------------------------------------------

def test_writable_allows_internal_write_then_rehardens(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    p.write_text("initial", encoding="utf-8")
    harden(p)
    assert is_hardened(p)

    with writable(p):
        # inside: mode must be writable (check portably — Windows reads 0o644 back as 0o666)
        assert os.access(p, os.W_OK)
        with open(p, "a", encoding="utf-8") as f:
            f.write("\nmore")

    # after: re-hardened
    assert is_hardened(p)
    assert p.read_text(encoding="utf-8") == "initial\nmore"


def test_writable_creates_new_file_and_hardens_it(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    assert not p.exists()
    with writable(p):
        p.write_text("fresh", encoding="utf-8")
    assert p.exists()
    assert is_hardened(p)


def test_writable_rehardens_even_on_exception(tmp_path: Path):
    p = tmp_path / "history.jsonl"
    p.write_text("x", encoding="utf-8")
    harden(p)

    with pytest.raises(RuntimeError):
        with writable(p):
            raise RuntimeError("boom")

    assert is_hardened(p)


# ---------------------------------------------------------------------------
# The end-to-end write-blocking property the regex can't guarantee
# ---------------------------------------------------------------------------

def test_external_writes_fail_after_harden(tmp_path: Path):
    """Once hardened, any caller that doesn't go through writable() is blocked."""
    p = tmp_path / "history.jsonl"
    p.write_text("line1", encoding="utf-8")
    harden(p)
    with pytest.raises(PermissionError):
        # Mirrors what ``tee /path/history.jsonl`` or ``echo > history.jsonl``
        # does under the hood after bash resolves the path.
        fd = os.open(p, os.O_WRONLY | os.O_APPEND)
        try:
            os.write(fd, b"pwned\n")
        finally:
            os.close(fd)
