"""Command rewriters for shell execution."""

from __future__ import annotations

import asyncio
import os
import shutil
from contextlib import suppress
from pathlib import Path

from loguru import logger
from pydantic import Field

from nanobot.config_base import Base


class RTKCommandRewriterConfig(Base):
    """RTK command rewrite configuration for exec."""

    enabled: bool = False
    path: str = "rtk"
    rewrite_timeout_ms: int = Field(default=2000, ge=1, le=60_000)
    tee_dir: str = ".nanobot/rtk-tee"


class RTKCommandRewriter:
    """Use ``rtk rewrite`` to wrap noisy developer commands."""

    _REWRITE_EXIT_CODES = {0, 3}

    def __init__(
        self,
        config: RTKCommandRewriterConfig,
        *,
        path_prepend: str = "",
        path_append: str = "",
    ) -> None:
        self.config = config
        self.path_prepend = path_prepend
        self.path_append = path_append

    async def rewrite(
        self,
        command: str,
        *,
        cwd: str,
        env: dict[str, str],
        workspace_root: str | None,
    ) -> str:
        if not self.config.enabled:
            return command

        executable = self._resolve_binary()
        if not executable:
            logger.debug("RTK command rewriter enabled but '{}' was not found", self.config.path)
            return command

        self._apply_tee_dir(env, cwd=cwd, workspace_root=workspace_root)

        try:
            returncode, stdout, stderr = await self._run_rewrite(executable, command, cwd, env)
        except asyncio.TimeoutError:
            logger.debug("RTK rewrite timed out after {}ms", self.config.rewrite_timeout_ms)
            return command
        except OSError as exc:
            logger.debug("RTK rewrite failed to start: {}", exc)
            return command

        if returncode not in self._REWRITE_EXIT_CODES:
            if stderr:
                logger.debug(
                    "RTK rewrite exited with {}: {}",
                    returncode,
                    stderr.decode("utf-8", errors="replace").strip()[:500],
                )
            return command

        rewritten = stdout.decode("utf-8", errors="replace").strip()
        if not rewritten or rewritten == command.strip():
            return command
        return rewritten

    def _resolve_binary(self) -> str | None:
        binary = (self.config.path or "rtk").strip() or "rtk"
        if os.sep in binary or (os.altsep and os.altsep in binary):
            return str(Path(binary).expanduser())

        path = self._compose_search_path(os.environ.get("PATH", ""))
        return shutil.which(binary, path=path)

    def _compose_search_path(self, current_path: str) -> str:
        parts = []
        if self.path_prepend:
            parts.append(self.path_prepend)
        if current_path:
            parts.append(current_path)
        if self.path_append:
            parts.append(self.path_append)
        return os.pathsep.join(parts)

    def _apply_tee_dir(
        self,
        env: dict[str, str],
        *,
        cwd: str,
        workspace_root: str | None,
    ) -> None:
        raw = self.config.tee_dir.strip()
        if not raw:
            return

        tee_dir = Path(raw).expanduser()
        if not tee_dir.is_absolute():
            tee_dir = Path(workspace_root or cwd).expanduser() / tee_dir

        try:
            tee_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.debug("Could not create RTK tee dir '{}': {}", tee_dir, exc)
            return
        env["RTK_TEE_DIR"] = str(tee_dir)

    async def _run_rewrite(
        self,
        executable: str,
        command: str,
        cwd: str,
        env: dict[str, str],
    ) -> tuple[int, bytes, bytes]:
        process = await asyncio.create_subprocess_exec(
            executable,
            "rewrite",
            command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.rewrite_timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            process.kill()
            with suppress(Exception):
                await process.wait()
            raise
        return process.returncode or 0, stdout, stderr


def filter_rtk_hook_warnings(text: str) -> str:
    """Remove RTK's hook-install reminder from auto-wrapped output."""
    if "[rtk]" not in text or "No hook installed" not in text:
        return text

    lines = text.splitlines()
    filtered = [
        line
        for line in lines
        if not (line.lstrip().startswith("[rtk]") and "No hook installed" in line)
    ]
    if not filtered:
        return ""
    suffix = "\n" if text.endswith(("\n", "\r\n")) else ""
    return "\n".join(filtered) + suffix
