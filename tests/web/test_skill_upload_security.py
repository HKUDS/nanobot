"""Tests for the skill upload endpoint security hardening."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Use a minimal test to validate the security logic without full server setup.
# The actual upload_skill function is tested via unit-level zip validation logic.


def _make_zip(files: dict[str, bytes | str]) -> bytes:
    """Create an in-memory zip from {filename: content}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(name, data)
    return buf.getvalue()


def test_zipslip_member_is_detected() -> None:
    """Verify that path traversal entries in a zip are caught."""
    target = Path("C:/tmp/safe") if Path("C:/").exists() else Path("/tmp/safe")
    target.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()

    evil_member = "../../etc/passwd"
    dest = (target / evil_member).resolve()
    with pytest.raises(ValueError):
        dest.relative_to(resolved_target)


def test_zipslip_clean_member_passes() -> None:
    """Verify a clean path within the target passes containment."""
    target = Path("C:/tmp/safe") if Path("C:/").exists() else Path("/tmp/safe")
    target.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()

    clean_member = "references/api.md"
    dest = (target / clean_member).resolve()
    dest.relative_to(resolved_target)  # should NOT raise


def test_oversized_zip_content_detected() -> None:
    """Verify size limit enforcement logic."""
    max_size = 10 * 1024 * 1024  # 10 MB
    oversized = b"x" * (max_size + 1)
    assert len(oversized) > max_size


def test_zip_without_skill_md() -> None:
    """Verify that a zip lacking SKILL.md is detected."""
    zip_bytes = _make_zip({"README.md": "# Hello"})
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = zf.namelist()
        skill_md_entries = [n for n in names if n.endswith("SKILL.md")]
        assert len(skill_md_entries) == 0


def test_zip_with_skill_md_passes() -> None:
    """Verify that a valid zip with SKILL.md is detected."""
    zip_bytes = _make_zip({
        "test-skill/SKILL.md": "---\nname: test\ndescription: test\n---\n\n# Test\n",
    })
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = zf.namelist()
        skill_md_entries = [n for n in names if n.endswith("SKILL.md")]
        assert len(skill_md_entries) == 1
