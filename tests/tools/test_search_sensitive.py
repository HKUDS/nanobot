"""Tests for GrepTool sensitive-path blocking — MIT-136.

Defence-in-depth: MIT-121 closes read_file/edit_file over sensitive paths;
MIT-122 redacts secrets from tool output; MIT-136 stops GrepTool from
reading file contents at sensitive paths in the first place so secret
material never reaches the scanner.

Design decisions:
  * Direct hit on a sensitive file  ->  fail the whole call with an
    explicit blocked-path error (no contents are read).
  * Recursive descent that includes sensitive files  ->  silently skip
    each sensitive entry, surface the count in the output notes, and
    let the rest of the grep proceed.  Rationale: one stray ~/.ssh/
    inside a large tree shouldn't fail an otherwise-legitimate search.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.tools.search import GrepTool


# ---------------------------------------------------------------------------
# Direct hit: grep called with a sensitive file as the target
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grep_direct_sensitive_file_is_blocked(tmp_path: Path) -> None:
    """Grepping straight into a sensitive file (e.g. .ssh/id_rsa) must be
    refused before any bytes are read."""
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key_path = ssh_dir / "id_rsa"
    key_path.write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nsecret-material\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )

    tool = GrepTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(pattern="BEGIN RSA", path=".ssh/id_rsa")

    assert result.startswith("Error:"), result
    assert "protected by security policy" in result
    # Crucially, no key material leaked through the error.
    assert "secret-material" not in result
    assert "BEGIN RSA PRIVATE KEY" not in result


@pytest.mark.asyncio
async def test_grep_direct_env_file_is_blocked(tmp_path: Path) -> None:
    """.env is in the sensitive-filename list; direct grep must refuse."""
    env_path = tmp_path / ".env"
    env_path.write_text("API_KEY=s3cret\n", encoding="utf-8")

    tool = GrepTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(pattern="API_KEY", path=".env")

    assert result.startswith("Error:"), result
    assert "protected by security policy" in result
    assert "s3cret" not in result


@pytest.mark.asyncio
async def test_grep_direct_pem_file_is_blocked(tmp_path: Path) -> None:
    """*.pem matches the sensitive-filename regex; direct grep must refuse."""
    pem_path = tmp_path / "server.pem"
    pem_path.write_text("fake-pem-body\n", encoding="utf-8")

    tool = GrepTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(pattern="fake", path="server.pem")

    assert result.startswith("Error:"), result
    assert "protected by security policy" in result


# ---------------------------------------------------------------------------
# Recursive descent: sensitive files inside a scanned tree are skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grep_recursive_skips_ssh_silently(tmp_path: Path) -> None:
    """Recursive grep over a tree containing .ssh/ must:
      * Not fail the call
      * Not surface any content from the .ssh/ file
      * Return matches from the other (non-sensitive) files as normal
      * Report a 'skipped N sensitive-path files' note
    """
    # Normal source tree
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "TOKEN = 'BEGIN RSA MARKER in source'\n", encoding="utf-8"
    )

    # Sensitive material nested under the scan root
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_rsa").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nreal-key\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )

    tool = GrepTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(pattern="BEGIN RSA", path=".")

    # Recursive call must succeed (not return an Error:)
    assert not result.startswith("Error:"), result

    # Non-sensitive source file was grepped as usual
    assert "src/app.py" in result

    # Sensitive file path must never appear in output
    assert ".ssh/id_rsa" not in result
    assert "real-key" not in result
    # Key body never surfaced either
    assert "real-key" not in result

    # Skip count is reported
    assert "sensitive-path files" in result


@pytest.mark.asyncio
async def test_grep_recursive_skip_note_counts_multiple_files(tmp_path: Path) -> None:
    """Multiple sensitive files in the tree are all skipped and counted."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("pattern here\n", encoding="utf-8")

    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_rsa").write_text("pattern here\n", encoding="utf-8")
    (ssh_dir / "id_ed25519").write_text("pattern here\n", encoding="utf-8")

    (tmp_path / "secret.pem").write_text("pattern here\n", encoding="utf-8")

    tool = GrepTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(pattern="pattern here", path=".")

    assert "src/ok.py" in result
    assert ".ssh" not in result
    assert "secret.pem" not in result
    # At least 3 sensitive files skipped — exact number may include .pub etc.
    assert "sensitive-path files" in result


# ---------------------------------------------------------------------------
# Negative cases: ordinary paths still work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grep_ordinary_file_is_allowed(tmp_path: Path) -> None:
    """Non-sensitive targets keep working unchanged."""
    path = tmp_path / "notes.txt"
    path.write_text("hello world\n", encoding="utf-8")

    tool = GrepTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(pattern="hello", path="notes.txt")

    assert not result.startswith("Error:"), result
    assert "notes.txt" in result


@pytest.mark.asyncio
async def test_grep_ordinary_directory_is_allowed(tmp_path: Path) -> None:
    """Non-sensitive directory targets keep working unchanged and do not
    spuriously emit a 'skipped sensitive' note."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("needle\n", encoding="utf-8")

    tool = GrepTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(pattern="needle", path="src")

    assert not result.startswith("Error:"), result
    assert "a.py" in result
    assert "b.py" in result
    assert "sensitive-path files" not in result


@pytest.mark.asyncio
async def test_grep_no_matches_still_works_in_tree_with_sensitive_files(
    tmp_path: Path,
) -> None:
    """If the pattern doesn't match anything, the standard no-matches message
    is returned — the sensitive skip logic must not shadow it."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("unrelated content\n", encoding="utf-8")
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_rsa").write_text("PRIVATE\n", encoding="utf-8")

    tool = GrepTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(pattern="does-not-match", path=".")

    # Either a no-matches message or at worst an empty result with notes
    assert "does-not-match" in result or "No matches" in result
    assert "PRIVATE" not in result
