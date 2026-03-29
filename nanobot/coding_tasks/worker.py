"""tmux-backed Codex worker launcher for coding tasks."""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nanobot.coding_tasks.harness import build_codex_bootstrap_prompt, detect_repo_harness
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.types import CodingTask
from nanobot.utils.helpers import ensure_dir

_SESSION_HINT_PATTERNS = (
    re.compile(r'"session_id"\s*:\s*"([^"]+)"'),
    re.compile(r'"sessionId"\s*:\s*"([^"]+)"'),
    re.compile(r"\bsessionId\s*[:=]\s*([A-Za-z0-9._:-]+)"),
    re.compile(r"\bsession(?:_id| id)?\s*[:=]\s*([A-Za-z0-9._:-]+)"),
)


@dataclass(slots=True)
class CodexLaunchResult:
    """Result of launching or reusing a Codex worker session."""

    task: CodingTask
    session_reused: bool
    command: str
    prompt_path: str
    log_path: str
    session_hint: str | None


class CodexWorkerLauncher:
    """Launch Codex workers in tmux and persist bootstrap metadata."""

    def __init__(
        self,
        workspace: Path,
        manager: CodexWorkerManager,
        *,
        codex_bin: str = "codex",
        tmux_bin: str = "tmux",
        socket_path: str | Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.workspace = workspace
        self.manager = manager
        self.codex_bin = codex_bin
        self.tmux_bin = tmux_bin
        self.socket_path = str(socket_path) if socket_path else None
        self.runner = runner or self._default_runner
        self.artifacts_dir = ensure_dir(workspace / "automation" / "coding" / "artifacts")

    def launch_task(self, task_id: str) -> CodexLaunchResult:
        """Launch a coding task in tmux or reuse the existing session."""
        task = self.manager.require_task(task_id)
        harness = detect_repo_harness(task.repo_path)
        harness_resolution = task.metadata.get("harness_conflict_resolution", "resume_existing")
        prompt = build_codex_bootstrap_prompt(
            repo_path=task.repo_path,
            goal=task.goal,
            branch_name=task.branch_name,
            approval_policy=task.approval_policy,
            harness=harness,
            harness_resolution=harness_resolution,
        )
        prompt_path = self._write_prompt_file(task, prompt)
        log_path = self._log_path(task)
        command = self.build_exec_command(task, prompt_path, log_path)

        session_name = task.tmux_session or ""
        session_reused = self._has_session(session_name)
        if not session_reused:
            self._new_session(session_name, task.repo_path)
        else:
            self._send_ctrl_c(session_name)

        self._send_literal(session_name, command)
        self._send_enter(session_name)

        pane_output = self.capture_pane(session_name)
        session_hint = self.extract_session_hint(pane_output)
        updated = self.manager.mark_starting(
            task.id,
            tmux_session=task.tmux_session,
            codex_session_hint=session_hint,
            harness_state=harness.harness_state,
            summary="Launching Codex worker",
        )
        return CodexLaunchResult(
            task=updated,
            session_reused=session_reused,
            command=command,
            prompt_path=str(prompt_path),
            log_path=str(log_path),
            session_hint=session_hint,
        )

    def build_exec_command(self, task: CodingTask, prompt_path: Path, log_path: Path) -> str:
        """Build the shell command that launches Codex for one coding task."""
        return (
            f"{shlex.quote(self.codex_bin)} exec --json --full-auto "
            f"-C {shlex.quote(task.repo_path)} - < {shlex.quote(str(prompt_path))} "
            f"| tee -a {shlex.quote(str(log_path))}"
        )

    def capture_pane(self, session: str, lines: int = 200) -> str:
        """Capture recent pane output from a tmux session."""
        result = self._run_tmux(
            "capture-pane",
            "-p",
            "-J",
            "-t",
            self._target(session),
            "-S",
            f"-{lines}",
            check=False,
        )
        return result.stdout or ""

    def has_session(self, session: str) -> bool:
        """Return True when the tmux session currently exists."""
        return self._has_session(session)

    def interrupt_task(self, task_id: str) -> CodingTask:
        """Send Ctrl-C to the tmux pane for an existing coding task."""
        task = self.manager.require_task(task_id)
        session_name = task.tmux_session or ""
        if not session_name or not self.has_session(session_name):
            raise RuntimeError(f"tmux session missing for coding task {task_id}")
        self._send_ctrl_c(session_name)
        return task

    @staticmethod
    def extract_session_hint(text: str) -> str | None:
        """Extract a Codex session hint from pane output when present."""
        for pattern in _SESSION_HINT_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1)
        return None

    def _write_prompt_file(self, task: CodingTask, prompt: str) -> Path:
        path = self.artifacts_dir / f"{task.id}.prompt.txt"
        path.write_text(prompt, encoding="utf-8")
        return path

    def _log_path(self, task: CodingTask) -> Path:
        return self.artifacts_dir / f"{task.id}.codex.log"

    def _has_session(self, session: str) -> bool:
        result = self._run_tmux("has-session", "-t", session, check=False)
        return result.returncode == 0

    def _new_session(self, session: str, cwd: str) -> None:
        self._run_tmux("new-session", "-d", "-s", session, "-c", cwd)

    def _send_ctrl_c(self, session: str) -> None:
        self._run_tmux("send-keys", "-t", self._target(session), "C-c")

    def _send_literal(self, session: str, command: str) -> None:
        self._run_tmux("send-keys", "-t", self._target(session), "-l", "--", command)

    def _send_enter(self, session: str) -> None:
        self._run_tmux("send-keys", "-t", self._target(session), "Enter")

    def _target(self, session: str) -> str:
        return f"{session}:0.0"

    def _run_tmux(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [self.tmux_bin]
        if self.socket_path:
            cmd.extend(["-S", self.socket_path])
        cmd.extend(args)
        return self.runner(cmd, check=check, capture_output=True, text=True)

    @staticmethod
    def _default_runner(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, **kwargs)
