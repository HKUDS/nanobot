"""Command-level rewrite hook.

============================================================================
  Command Rewrite Hook
  ----------------------------------------------------------------------
  横切工具参数改写层。hook 在 runner 调用 _execute_tools 之前拦截
  tool_calls，对特定工具的参数做等价改写——零工具耦合，未来可扩展。

  当前策略: rtk 命令压缩 (节省 60–90% token)。
  未来可扩展: SQL 脱敏 / 路径归一化 / 敏感词拦截。
============================================================================
"""

from __future__ import annotations

import asyncio
import os

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext


class CommandRewriteHook(AgentHook):
    """Rewrite ``exec`` tool-call commands via an external rewriter (``rtk``).

    Fail-safe: if the rewriter is unavailable, times out, or returns a
    non-zero exit code, the original command passes through unchanged.
    """

    __slots__ = ("_enabled", "_verbose", "_timeout", "_path_append")

    def __init__(
        self,
        *,
        enabled: bool = False,
        verbose: bool = False,
        timeout: float = 5.0,
        path_append: str = "",
    ) -> None:
        self._enabled = enabled
        self._verbose = verbose
        self._timeout = timeout
        self._path_append = path_append

    # ─── lifecycle ──────────────────────────────────────────────────────
    async def before_execute_tools(self, context: AgentHookContext) -> None:
        if not self._enabled:
            return
        for tc in context.tool_calls:
            if tc.name != "exec":
                continue
            cmd = tc.arguments.get("command")
            if not isinstance(cmd, str) or not cmd.strip():
                continue
            rewritten = await self._rewrite(cmd)
            if rewritten and rewritten != cmd:
                tc.arguments["command"] = rewritten
                if self._verbose:
                    logger.debug("rtk rewrite: {} → {}", cmd, rewritten)

    # ─── rewriter ───────────────────────────────────────────────────────
    async def _rewrite(self, command: str) -> str:
        try:
            env = os.environ.copy()
            if self._path_append:
                env["PATH"] = env.get("PATH", "") + os.pathsep + self._path_append
            proc = await asyncio.create_subprocess_exec(
                "rtk", "rewrite", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
            if proc.returncode == 0 and stdout:
                return stdout.decode().strip()
        except Exception as e:  # noqa: BLE001 — fail-safe is the whole point
            logger.debug("rtk rewrite failed (passthrough): {}", e)
        return command
