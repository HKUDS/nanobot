import time
from pathlib import Path
import pytest
from nanobot.agent.context import ContextBuilder

@pytest.fixture
def ctx(tmp_path):
    return ContextBuilder(workspace=tmp_path)

def test_cache_returns_same_on_unchanged(ctx, tmp_path):
    (tmp_path / "SOUL.md").write_text("I am calm.")
    r1 = ctx._load_bootstrap_files()
    r2 = ctx._load_bootstrap_files()
    assert r1 == r2
    assert "I am calm." in r1

def test_cache_invalidates_on_mtime_change(ctx, tmp_path):
    soul = tmp_path / "SOUL.md"
    soul.write_text("v1")
    r1 = ctx._load_bootstrap_files()
    time.sleep(0.05)
    soul.write_text("v2")
    r2 = ctx._load_bootstrap_files()
    assert "v1" in r1
    assert "v2" in r2

def test_handles_missing_files(ctx):
    assert ctx._load_bootstrap_files() == ""

def test_handles_deleted_file(ctx, tmp_path):
    soul = tmp_path / "SOUL.md"
    soul.write_text("temp")
    ctx._load_bootstrap_files()
    soul.unlink()
    result = ctx._load_bootstrap_files()
    assert "temp" not in result
