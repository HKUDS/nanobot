"""Tests for nanobot.cli.service module."""

import os
import platform
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.cli.service import (
    SERVICE_NAME,
    SYSTEMD_USER_DIR,
    check_linger_enabled,
    check_linux_systemd,
    generate_service_unit,
    get_nanobot_executable,
    get_service_file_path,
)
from nanobot.cli.service import app as service_app

runner = CliRunner()


class TestServicePaths:
    """Test path-related functions."""

    def test_get_service_file_path(self):
        """Service file should be in ~/.config/systemd/user/."""
        path = get_service_file_path()
        assert path == SYSTEMD_USER_DIR / f"{SERVICE_NAME}.service"
        # Check path components (works on both Windows and Linux)
        assert path.parent.name == "user"
        assert path.parent.parent.name == "systemd"
        assert path.parent.parent.parent.name == ".config"
        assert path.name == "nanobot.service"


class TestGetNanobotExecutable:
    """Test nanobot executable detection."""

    def test_finds_nanobot_in_path(self):
        """Should find nanobot if it exists in PATH."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/nanobot"
            result = get_nanobot_executable()
            assert result == "/usr/bin/nanobot"

    def test_fallback_to_python_module(self):
        """Should fallback to python -m nanobot if nanobot not in PATH."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            # First call (nanobot) returns None, second (python3) returns path
            mock_which.side_effect = [None, "/usr/bin/python3"]
            result = get_nanobot_executable()
            assert result == "/usr/bin/python3 -m nanobot"

    def test_fallback_to_python(self):
        """Should try python if python3 not found."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.side_effect = [None, None, "/usr/bin/python"]
            result = get_nanobot_executable()
            assert result == "/usr/bin/python -m nanobot"

    def test_raises_if_nothing_found(self):
        """Should raise if no executable found."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.return_value = None
            with pytest.raises(RuntimeError, match="Cannot find nanobot"):
                get_nanobot_executable()


class TestGenerateServiceUnit:
    """Test systemd service unit generation."""

    def test_basic_structure(self):
        """Generated unit should have all required sections."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/nanobot"
            unit = generate_service_unit()

        assert "[Unit]" in unit
        assert "[Service]" in unit
        assert "[Install]" in unit

    def test_contains_description(self):
        """Unit should have a description."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/nanobot"
            unit = generate_service_unit()

        assert "Description=" in unit
        assert "Nanobot" in unit

    def test_exec_start_with_simple_path(self):
        """ExecStart should use direct path when found in PATH."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/nanobot"
            unit = generate_service_unit()

        assert "ExecStart=/usr/bin/nanobot gateway" in unit

    def test_exec_start_with_python_module(self):
        """ExecStart should use bash -c for python -m style."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.side_effect = [None, "/usr/bin/python3"]
            unit = generate_service_unit()

        assert "ExecStart=/bin/bash -c '/usr/bin/python3 -m nanobot gateway'" in unit

    def test_restart_policy(self):
        """Unit should have restart-on-failure policy."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/nanobot"
            unit = generate_service_unit()

        assert "Restart=on-failure" in unit
        assert "RestartSec=5" in unit

    def test_logging_to_journal(self):
        """Unit should log to journald."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/nanobot"
            unit = generate_service_unit()

        assert "StandardOutput=journal" in unit
        assert "StandardError=journal" in unit

    def test_install_target(self):
        """Unit should be wanted by default.target."""
        with patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/nanobot"
            unit = generate_service_unit()

        assert "WantedBy=default.target" in unit


class TestCheckLinuxSystemd:
    """Test Linux/systemd availability check."""

    def test_returns_false_on_non_linux(self):
        """Should return False on non-Linux platforms."""
        with patch("nanobot.cli.service.platform.system") as mock_system:
            mock_system.return_value = "Windows"
            result = check_linux_systemd()
            assert result is False

    def test_returns_false_if_no_systemctl(self):
        """Should return False if systemctl not found."""
        with patch("nanobot.cli.service.platform.system") as mock_system, \
             patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_system.return_value = "Linux"
            mock_which.return_value = None
            result = check_linux_systemd()
            assert result is False

    def test_returns_true_on_linux_with_systemd(self):
        """Should return True on Linux with systemctl."""
        with patch("nanobot.cli.service.platform.system") as mock_system, \
             patch("nanobot.cli.service.shutil.which") as mock_which:
            mock_system.return_value = "Linux"
            mock_which.return_value = "/usr/bin/systemctl"
            result = check_linux_systemd()
            assert result is True


class TestCheckLingerEnabled:
    """Test linger status check."""

    def test_returns_false_if_no_user_env(self):
        """Should return False if USER env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove USER from environment
            os.environ.pop("USER", None)
            result = check_linger_enabled()
            assert result is False

    def test_returns_false_if_linger_file_missing(self):
        """Should return False if linger file doesn't exist."""
        with patch.dict(os.environ, {"USER": "testuser"}), \
             patch("nanobot.cli.service.Path.exists") as mock_exists:
            mock_exists.return_value = False
            result = check_linger_enabled()
            assert result is False

    def test_returns_true_if_linger_file_exists(self):
        """Should return True if linger file exists."""
        with patch.dict(os.environ, {"USER": "testuser"}), \
             patch("nanobot.cli.service.Path.exists") as mock_exists:
            mock_exists.return_value = True
            result = check_linger_enabled()
            assert result is True


class TestServiceCommands:
    """Test CLI commands."""

    def test_status_shows_not_installed_on_non_linux(self):
        """Status command should show error on non-Linux."""
        with patch("nanobot.cli.service.check_linux_systemd") as mock_check:
            mock_check.return_value = False
            result = runner.invoke(service_app, ["status"])
            # Should exit with error on non-Linux
            assert result.exit_code != 0 or "only supported on Linux" in result.stdout

    def test_install_rejected_on_non_linux(self):
        """Install command should be rejected on non-Linux."""
        with patch("nanobot.cli.service.check_linux_systemd") as mock_check:
            mock_check.return_value = False
            result = runner.invoke(service_app, ["install"])
            assert result.exit_code != 0
            # Just check exit code is non-zero (error occurred)
            # The error message goes to console via rich, not captured in stdout

    def test_uninstall_rejected_on_non_linux(self):
        """Uninstall command should be rejected on non-Linux."""
        with patch("nanobot.cli.service.check_linux_systemd") as mock_check:
            mock_check.return_value = False
            result = runner.invoke(service_app, ["uninstall"])
            assert result.exit_code != 0

    def test_restart_rejected_on_non_linux(self):
        """Restart command should be rejected on non-Linux."""
        with patch("nanobot.cli.service.check_linux_systemd") as mock_check:
            mock_check.return_value = False
            result = runner.invoke(service_app, ["restart"])
            assert result.exit_code != 0

    def test_logs_rejected_on_non_linux(self):
        """Logs command should be rejected on non-Linux."""
        with patch("nanobot.cli.service.check_linux_systemd") as mock_check:
            mock_check.return_value = False
            result = runner.invoke(service_app, ["logs"])
            assert result.exit_code != 0


class TestServiceInstall:
    """Test service installation."""

    def test_install_creates_service_file(self, tmp_path):
        """Install should create systemd service file."""
        service_dir = tmp_path / ".config" / "systemd" / "user"
        service_file = service_dir / "nanobot.service"

        with patch("nanobot.cli.service.check_linux_systemd") as mock_check, \
             patch("nanobot.cli.service.SYSTEMD_USER_DIR", service_dir), \
             patch("nanobot.cli.service.get_service_file_path") as mock_path, \
             patch("nanobot.cli.service.shutil.which") as mock_which, \
             patch("nanobot.cli.service.run_systemctl_user") as mock_run, \
             patch("nanobot.cli.service.check_linger_enabled") as mock_linger:

            mock_check.return_value = True
            mock_path.return_value = service_file
            mock_which.return_value = "/usr/bin/nanobot"
            mock_run.return_value = MagicMock(returncode=0)
            mock_linger.return_value = True

            result = runner.invoke(service_app, ["install"])

            assert result.exit_code == 0
            assert service_file.exists()
            content = service_file.read_text()
            assert "[Unit]" in content
            assert "[Service]" in content

    def test_install_shows_linger_warning(self, tmp_path):
        """Install should warn if linger is not enabled."""
        service_dir = tmp_path / ".config" / "systemd" / "user"
        service_file = service_dir / "nanobot.service"

        with patch("nanobot.cli.service.check_linux_systemd") as mock_check, \
             patch("nanobot.cli.service.SYSTEMD_USER_DIR", service_dir), \
             patch("nanobot.cli.service.get_service_file_path") as mock_path, \
             patch("nanobot.cli.service.shutil.which") as mock_which, \
             patch("nanobot.cli.service.run_systemctl_user") as mock_run, \
             patch("nanobot.cli.service.check_linger_enabled") as mock_linger:

            mock_check.return_value = True
            mock_path.return_value = service_file
            mock_which.return_value = "/usr/bin/nanobot"
            mock_run.return_value = MagicMock(returncode=0)
            mock_linger.return_value = False

            result = runner.invoke(service_app, ["install"])

            assert "Linger is not enabled" in result.stdout


class TestServiceUninstall:
    """Test service uninstallation."""

    def test_uninstall_removes_service_file(self, tmp_path):
        """Uninstall should remove the service file."""
        service_dir = tmp_path / ".config" / "systemd" / "user"
        service_dir.mkdir(parents=True)
        service_file = service_dir / "nanobot.service"
        service_file.write_text("[Unit]\nDescription=Test\n")

        with patch("nanobot.cli.service.check_linux_systemd") as mock_check, \
             patch("nanobot.cli.service.get_service_file_path") as mock_path, \
             patch("nanobot.cli.service.run_systemctl_user") as mock_run:

            mock_check.return_value = True
            mock_path.return_value = service_file
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(service_app, ["uninstall"])

            assert result.exit_code == 0
            assert not service_file.exists()

    def test_uninstall_handles_missing_service(self):
        """Uninstall should handle case where service is not installed."""
        with patch("nanobot.cli.service.check_linux_systemd") as mock_check, \
             patch("nanobot.cli.service.get_service_file_path") as mock_path, \
             patch("nanobot.cli.service.run_systemctl_user") as mock_run:

            mock_check.return_value = True
            mock_path.return_value = Path("/nonexistent/nanobot.service")
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(service_app, ["uninstall"])

            assert "Service not installed" in result.stdout
