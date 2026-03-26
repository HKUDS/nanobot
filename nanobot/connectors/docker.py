"""Docker Compose-backed connector runtime."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.schema import DockerConnectorConfig, MCPServerConfig
from nanobot.connectors.base import BaseConnector


class DockerConnector(BaseConnector):
    """Manage a connector exposed as one or more Docker Compose services."""

    def __init__(self, name: str, config: DockerConnectorConfig, workspace: Path):
        super().__init__(name)
        self.config = config
        self.workspace = workspace

    def start(self) -> None:
        compose_file = self._compose_file()
        cmd = self._compose_base_cmd(compose_file)
        cmd.extend(["up", "-d", *self.config.up_args, *self.config.services])
        self._run(cmd, compose_file)
        wait_s = max(0.0, float(self.config.wait_for_seconds))
        if wait_s:
            time.sleep(wait_s)
        logger.info("Connector '{}' started", self.name)

    def stop(self, force: bool = False) -> None:
        if not force and not self.config.stop_on_exit:
            return
        compose_file = self._compose_file()
        cmd = self._compose_base_cmd(compose_file)
        if self.config.services and not force:
            cmd.extend(["stop", *self.config.down_args, *self.config.services])
        else:
            cmd.extend(["down", *self.config.down_args])
        self._run(cmd, compose_file)
        logger.info("Connector '{}' stopped", self.name)

    def status(self) -> dict[str, Any]:
        compose_file = self._compose_file()
        cmd = self._compose_base_cmd(compose_file)
        cmd.extend(["ps", "--services", "--status", "running"])
        try:
            result = self._run(cmd, compose_file)
        except Exception as exc:
            return {
                "enabled": self.config.enabled,
                "type": self.config.type,
                "running": False,
                "error": str(exc),
            }

        running_services = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        expected_services = self.config.services or running_services
        running = bool(running_services) and all(service in running_services for service in expected_services)
        return {
            "enabled": self.config.enabled,
            "type": self.config.type,
            "compose_file": str(compose_file),
            "project_name": self.config.project_name or "",
            "services": expected_services,
            "running_services": running_services,
            "running": running,
        }

    def mcp_servers(self) -> dict[str, MCPServerConfig]:
        return self.config.mcp_servers

    def _compose_file(self) -> Path:
        raw = (self.config.compose_file or "").strip()
        if not raw:
            raise ValueError(f"Connector '{self.name}' is missing compose_file")
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not path.is_absolute():
            path = (self.workspace / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Connector '{self.name}' compose file not found: {path}")
        return path

    def _working_dir(self, compose_file: Path) -> Path:
        raw = (self.config.working_dir or "").strip()
        if raw:
            path = Path(os.path.expandvars(os.path.expanduser(raw)))
            return path if path.is_absolute() else (self.workspace / path).resolve()
        return compose_file.parent

    def _compose_base_cmd(self, compose_file: Path) -> list[str]:
        cmd = ["docker", "compose", "-f", str(compose_file)]
        if self.config.project_name:
            cmd.extend(["-p", self.config.project_name])
        return cmd

    def _command_env(self) -> dict[str, str]:
        env = os.environ.copy()
        substitutions = {
            "WORKSPACE": str(self.workspace),
            "CONNECTOR_NAME": self.name,
        }
        for key, value in (self.config.env or {}).items():
            expanded = os.path.expanduser(os.path.expandvars(value))
            for token, replacement in substitutions.items():
                expanded = expanded.replace(f"${{{token}}}", replacement)
            env[key] = expanded
        return env

    def _run(self, cmd: list[str], compose_file: Path) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            cmd,
            cwd=self._working_dir(compose_file),
            env=self._command_env(),
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(stderr or f"Command failed: {' '.join(cmd)}")
        return result
