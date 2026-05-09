"""Tests for nanobot/skills/create-instance/scripts/create_instance.py."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "nanobot" / "skills" / "create-instance" / "scripts" / "create_instance.py"


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME at a temp dir so nanobot writes configs there."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("NANOBOT_CONFIG", raising=False)
    return tmp_path


def _run_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run create_instance.py as a subprocess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )


class TestValidation:
    """Argument validation tests."""

    def test_missing_required_args_exits_with_error(self) -> None:
        result = _run_script()
        assert result.returncode != 0

    def test_invalid_channel_exits_with_error(self, tmp_home: Path) -> None:
        result = _run_script("--name", "test", "--channel", "nonexistent_channel")
        assert result.returncode != 0
        assert "nonexistent_channel" in result.stderr or "nonexistent_channel" in result.stdout


class TestCreateInstance:
    """End-to-end instance creation tests."""

    def test_creates_config_and_workspace(self, tmp_home: Path) -> None:
        config_dir = tmp_home / ".nanobot-test"
        result = _run_script(
            "--name", "test-bot",
            "--channel", "telegram",
            "--config-dir", str(config_dir),
        )
        assert result.returncode == 0, result.stderr

        config_path = config_dir / "config.json"
        assert config_path.exists(), f"Config not created at {config_path}"

        workspace = config_dir / "workspace"
        assert workspace.exists(), f"Workspace not created at {workspace}"

    def test_config_has_channel_enabled(self, tmp_home: Path) -> None:
        config_dir = tmp_home / ".nanobot-test"
        result = _run_script(
            "--name", "test-bot",
            "--channel", "telegram",
            "--config-dir", str(config_dir),
        )
        assert result.returncode == 0, result.stderr

        data = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert data["channels"]["telegram"]["enabled"] is True

    def test_config_workspace_path_set(self, tmp_home: Path) -> None:
        config_dir = tmp_home / ".nanobot-test"
        result = _run_script(
            "--name", "test-bot",
            "--channel", "telegram",
            "--config-dir", str(config_dir),
        )
        assert result.returncode == 0, result.stderr

        data = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        ws = data["agents"]["defaults"]["workspace"]
        assert str(config_dir / "workspace") in ws or "workspace" in ws

    def test_model_override(self, tmp_home: Path) -> None:
        config_dir = tmp_home / ".nanobot-test"
        result = _run_script(
            "--name", "test-bot",
            "--channel", "telegram",
            "--model", "deepseek/deepseek-chat",
            "--config-dir", str(config_dir),
        )
        assert result.returncode == 0, result.stderr

        data = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert data["agents"]["defaults"]["model"] == "deepseek/deepseek-chat"

    def test_rejects_duplicate_instance(self, tmp_home: Path) -> None:
        config_dir = tmp_home / ".nanobot-test"
        result1 = _run_script(
            "--name", "test-bot",
            "--channel", "telegram",
            "--config-dir", str(config_dir),
        )
        assert result1.returncode == 0

        result2 = _run_script(
            "--name", "test-bot",
            "--channel", "telegram",
            "--config-dir", str(config_dir),
        )
        assert result2.returncode != 0

    def test_port_reassigned_when_default_in_use(self, tmp_home: Path) -> None:
        """When default gateway port is occupied, script should pick a different one."""
        config_dir = tmp_home / ".nanobot-test"

        # Bind to the default gateway port to simulate a running instance
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
            blocker.bind(("127.0.0.1", 18790))
            blocker.listen(1)

            result = _run_script(
                "--name", "test-bot",
                "--channel", "telegram",
                "--config-dir", str(config_dir),
            )
            assert result.returncode == 0, result.stderr

        data = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert data["gateway"]["port"] != 18790

    def test_inherits_api_key_from_current_instance(self, tmp_home: Path) -> None:
        """API keys from --inherit-config should be copied to new instance."""
        # Create a fake "current instance" config with an API key
        src_dir = tmp_home / ".nanobot-current"
        src_dir.mkdir()
        src_config = src_dir / "config.json"
        src_config.write_text(json.dumps({
            "providers": {
                "anthropic": {"apiKey": "sk-test-key-12345"},
                "deepseek": {"apiKey": "dsk-another-key"},
                "openai": {},  # no key, should not be copied
            },
        }), encoding="utf-8")

        config_dir = tmp_home / ".nanobot-new"
        result = _run_script(
            "--name", "new-bot",
            "--channel", "telegram",
            "--config-dir", str(config_dir),
            "--inherit-config", str(src_config),
        )
        assert result.returncode == 0, result.stderr

        data = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        providers = data.get("providers", {})
        assert providers.get("anthropic", {}).get("apiKey") == "sk-test-key-12345"
        assert providers.get("deepseek", {}).get("apiKey") == "dsk-another-key"
        # openai had no key, so it should not be in the new config's providers
        assert providers.get("openai", {}).get("apiKey") is None
