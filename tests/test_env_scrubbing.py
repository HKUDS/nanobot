"""Tests for environment variable scrubbing in ExecTool."""

import os
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from nanobot.agent.tools.shell import ExecTool


class TestIsSensitiveEnv:
    """Tests for ExecTool._is_sensitive_env()."""

    @pytest.mark.parametrize("name", [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "BRAVE_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "GITHUB_TOKEN",
        "APP_SECRET",
        "CLIENT_SECRET",
        "FEISHU_APP_SECRET",
        "SMTP_PASSWORD",
        "DB_PASSWORD",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "DATABASE_URL",
        "DSN",
        # Case insensitive
        "anthropic_api_key",
        "database_url",
    ])
    def test_identifies_sensitive_names(self, name: str) -> None:
        assert ExecTool._is_sensitive_env(name) is True

    @pytest.mark.parametrize("name", [
        "PATH",
        "HOME",
        "LANG",
        "USER",
        "SHELL",
        "TERM",
        "EDITOR",
        "PWD",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    ])
    def test_allows_non_sensitive_names(self, name: str) -> None:
        assert ExecTool._is_sensitive_env(name) is False


class TestExecEnvFiltering:
    """Tests that execute() passes a filtered env to the subprocess."""

    @pytest.mark.asyncio
    async def test_execute_filters_sensitive_env_vars(self) -> None:
        tool = ExecTool()

        mock_process = MagicMock()
        mock_process.communicate = AsyncMock(return_value=(b"hello", b""))
        mock_process.returncode = 0

        fake_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "ANTHROPIC_API_KEY": "sk-secret-123",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "LANG": "en_US.UTF-8",
        }

        with patch.dict(os.environ, fake_env, clear=True), \
             patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=mock_process) as mock_shell:
            await tool.execute("echo hello")

            call_kwargs = mock_shell.call_args
            env_passed = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
            assert env_passed is not None
            assert "PATH" in env_passed
            assert "HOME" in env_passed
            assert "LANG" in env_passed
            assert "ANTHROPIC_API_KEY" not in env_passed
            assert "DATABASE_URL" not in env_passed
