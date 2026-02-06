"""Heartbeat service - periodic agent wake-up to check for tasks."""

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

from nanobot.providers.base import LLMProvider

# Default interval: 30 minutes
DEFAULT_HEARTBEAT_INTERVAL_S = 30 * 60

# The prompt sent to agent during heartbeat
HEARTBEAT_PROMPT = """Read HEARTBEAT.md in your workspace (if it exists).
Follow any instructions or tasks listed there.
If nothing needs attention, reply with just: HEARTBEAT_OK"""

# Token that indicates "nothing to do"
HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"

TRIAGE_PROMPT_TEMPLATE = """\
You are a task triage agent. Analyze this context and decide if the main \
agent should act.

## Strategy File ({strategy_file})
{strategy_content}

## Git Status
{git_status}

## Active Sessions
{tmux_sessions}

Respond with JSON only: {{"act": true/false, "reason": "...", \
"priority": "low/medium/high"}}
Rules:
- act=true only if there are clear, actionable tasks
- Checked/completed items (- [x]) are NOT actionable
- Empty/missing strategy file means act=false"""

EXECUTION_PROMPT_TEMPLATE = """\
[Daemon Mode - Priority: {priority}]

Triage reason: {reason}

## Strategy
{strategy_content}

## Current State
Git: {git_status}
Sessions: {tmux_sessions}

Execute the highest priority task from the strategy file. \
Use available tools including tmux for persistent shells. \
Mark completed tasks with [x] in the strategy file."""


def _is_heartbeat_empty(content: str | None) -> bool:
    """Check if HEARTBEAT.md has no actionable content."""
    if not content:
        return True

    # Lines to skip: empty, headers, HTML comments, empty checkboxes
    skip_patterns = {"- [ ]", "* [ ]", "- [x]", "* [x]"}

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("<!--") or line in skip_patterns:
            continue
        return False  # Found actionable content

    return True


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    The agent reads HEARTBEAT.md from the workspace and executes any
    tasks listed there. If nothing needs attention, it replies HEARTBEAT_OK.

    In daemon mode (when triage_provider is set), uses a three-tier pipeline:
    - Tier 0: Gather context (strategy file, git status, tmux sessions)
    - Tier 1: Triage via cheap LLM call to decide whether to act
    - Tier 2: Execute via the main agent loop
    """

    def __init__(
        self,
        workspace: Path,
        on_heartbeat: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
        enabled: bool = True,
        triage_provider: LLMProvider | None = None,
        triage_model: str | None = None,
        execution_model: str | None = None,
        strategy_file: str = "HEARTBEAT.md",
        max_iterations: int = 25,
        cooldown_after_action: int = 600,
    ):
        self.workspace = workspace
        self.on_heartbeat = on_heartbeat
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None

        # Daemon mode params
        self._triage_provider = triage_provider
        self._triage_model = triage_model
        self._execution_model = execution_model
        self._strategy_file = strategy_file
        self._max_iterations = max_iterations
        self._cooldown_s = cooldown_after_action
        self._last_action_time: float = 0
        self._daemon_mode = triage_provider is not None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / self._strategy_file

    def _read_heartbeat_file(self) -> str | None:
        """Read strategy file content."""
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        mode = "daemon" if self._daemon_mode else "legacy"
        logger.info(f"Heartbeat started (every {self.interval_s}s, mode={mode})")

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        if self._daemon_mode:
            await self._daemon_tick()
            return

        # Legacy path
        content = self._read_heartbeat_file()

        if _is_heartbeat_empty(content):
            logger.debug("Heartbeat: no tasks (strategy file empty)")
            return

        logger.info("Heartbeat: checking for tasks...")

        if self.on_heartbeat:
            try:
                response = await self.on_heartbeat(HEARTBEAT_PROMPT)

                if HEARTBEAT_OK_TOKEN.replace("_", "") in response.upper().replace("_", ""):
                    logger.info("Heartbeat: OK (no action needed)")
                else:
                    logger.info("Heartbeat: completed task")

            except Exception as e:
                logger.error(f"Heartbeat execution failed: {e}")

    # ------------------------------------------------------------------
    # Daemon three-tier pipeline
    # ------------------------------------------------------------------

    async def _gather_context(self) -> dict[str, Any]:
        """Tier 0: Gather context from strategy file, git, and tmux."""
        strategy_content: str | None = None
        git_status: str | None = None
        tmux_sessions: str | None = None

        # Read strategy file
        try:
            sf = self.workspace / self._strategy_file
            if sf.exists():
                strategy_content = sf.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Tier 0: failed to read strategy file: {e}")

        # Git status
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "status",
                "--porcelain",
                "--branch",
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                git_status = stdout.decode("utf-8").strip()
        except Exception as e:
            logger.warning(f"Tier 0: git status failed: {e}")

        # Tmux sessions
        try:
            socket_path = Path(tempfile.gettempdir()) / "nanobot-tmux-sockets" / "nanobot.sock"
            if socket_path.exists():
                proc = await asyncio.create_subprocess_exec(
                    "tmux",
                    "-S",
                    str(socket_path),
                    "list-sessions",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    tmux_sessions = stdout.decode("utf-8").strip()
        except Exception as e:
            logger.warning(f"Tier 0: tmux check failed: {e}")

        has_signals = bool(strategy_content) or bool(tmux_sessions)

        return {
            "strategy_content": strategy_content,
            "git_status": git_status,
            "tmux_sessions": tmux_sessions,
            "has_signals": has_signals,
        }

    async def _triage(self, context: dict[str, Any]) -> dict[str, Any]:
        """Tier 1: Triage context with a cheap LLM call."""
        try:
            prompt = TRIAGE_PROMPT_TEMPLATE.format(
                strategy_file=self._strategy_file,
                strategy_content=(context["strategy_content"] or "No strategy file found."),
                git_status=context["git_status"] or "Not a git repository.",
                tmux_sessions=(context["tmux_sessions"] or "No active sessions."),
            )

            assert self._triage_provider is not None
            response = await self._triage_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._triage_model,
                temperature=0.2,
                max_tokens=256,
            )

            raw = (response.content or "").strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw

            result = json.loads(raw)
            return {
                "act": bool(result.get("act", False)),
                "reason": str(result.get("reason", "")),
                "priority": str(result.get("priority", "low")),
            }
        except Exception as e:
            logger.warning(f"Tier 1: triage failed: {e}")
            return {"act": False, "reason": "parse error"}

    async def _execute_daemon_action(
        self,
        context: dict[str, Any],
        triage: dict[str, Any],
    ) -> None:
        """Tier 2: Execute action via the main agent loop."""
        elapsed = time.time() - self._last_action_time
        if elapsed < self._cooldown_s:
            remaining = int(self._cooldown_s - elapsed)
            logger.info(f"Tier 2: cooldown active, {remaining}s remaining")
            return

        prompt = EXECUTION_PROMPT_TEMPLATE.format(
            priority=triage.get("priority", "low"),
            reason=triage.get("reason", ""),
            strategy_content=(context["strategy_content"] or "No strategy file."),
            git_status=context["git_status"] or "N/A",
            tmux_sessions=context["tmux_sessions"] or "No active sessions.",
        )

        try:
            if self.on_heartbeat:
                await self.on_heartbeat(prompt)
            self._last_action_time = time.time()
            logger.info("Tier 2: daemon action executed")
        except Exception as e:
            logger.warning(f"Tier 2: execution failed: {e}")

    async def _daemon_tick(self) -> None:
        """Orchestrator: run the three-tier daemon pipeline."""
        # Tier 0: gather context
        try:
            context = await self._gather_context()
        except Exception as e:
            logger.warning(f"Daemon tick: context gathering failed: {e}")
            return

        if not context["has_signals"]:
            logger.debug("Daemon tick: no signals detected")
            return

        # Tier 1: triage
        try:
            triage = await self._triage(context)
        except Exception as e:
            logger.warning(f"Daemon tick: triage failed: {e}")
            return

        if not triage.get("act"):
            logger.info(f"Daemon tick: no action needed - {triage.get('reason')}")
            return

        # Tier 2: execute
        try:
            await self._execute_daemon_action(context, triage)
        except Exception as e:
            logger.warning(f"Daemon tick: execution failed: {e}")

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        if self.on_heartbeat:
            return await self.on_heartbeat(HEARTBEAT_PROMPT)
        return None
