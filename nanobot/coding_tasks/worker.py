"""tmux-backed Codex worker launcher for coding tasks."""

from __future__ import annotations

import os
import re
import shlex
import shutil
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

_WORKER_ENV_KEYS = (
    "HOME",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
)
_DEFAULT_PATH_SEGMENTS = (
    "/Applications/Codex.app/Contents/Resources",
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)
_CODEX_CONFIG_OVERRIDES = (
    'model_reasoning_summary="detailed"',
)
_STARTUP_DIAGNOSTICS = (
    (
        ("current working directory must be readable", "brew"),
        "Worker shell bootstrap failed before Codex launch; the shell tried to initialize brew from an unreadable cwd.",
    ),
    (
        ("unsupported value", "reasoning.summary"),
        "Codex rejected the inherited reasoning-summary setting before work began.",
    ),
    (
        ("operation not permitted",),
        "Worker hit an operation-not-permitted error before Codex emitted JSON events.",
    ),
)


@dataclass(slots=True)
class CodexLaunchResult:
    """Result of launching or reusing a Codex worker session."""

    task: CodingTask
    session_reused: bool
    command: str
    launch_script_path: str
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
        self.codex_bin = self._resolve_codex_bin(codex_bin)
        self.tmux_bin = tmux_bin
        self.socket_path = str(socket_path) if socket_path else self._default_socket_path()
        self.runner = runner or self._default_runner
        self.artifacts_dir = ensure_dir(workspace / "automation" / "coding" / "artifacts")
        self.shell_bin = "/bin/sh"
        self.shell_env = self._build_shell_env()
        self.launch_cwd = self._resolve_launch_cwd()

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
        launch_script_path = self._write_launch_script(task, prompt_path, log_path)
        command = self.build_exec_command(task, launch_script_path)

        session_name = task.tmux_session or ""
        session_reused = self._has_session(session_name)
        if not session_reused:
            self._new_session(session_name, command)
        else:
            self._respawn_session(session_name, command)

        pane_output = self.capture_pane(session_name)
        session_hint = self.extract_session_hint(pane_output)
        launch_summary = self.summarize_startup_diagnostic(pane_output) or "Launching Codex worker"
        updated = self.manager.mark_starting(
            task.id,
            tmux_session=task.tmux_session,
            codex_session_hint=session_hint,
            harness_state=harness.harness_state,
            summary=launch_summary,
        )
        return CodexLaunchResult(
            task=updated,
            session_reused=session_reused,
            command=command,
            launch_script_path=str(launch_script_path),
            prompt_path=str(prompt_path),
            log_path=str(log_path),
            session_hint=session_hint,
        )

    def build_exec_command(self, task: CodingTask, launch_script_path: Path) -> str:
        """Build the short shell command that launches one task-specific script."""
        return f"{shlex.quote(self.shell_bin)} {shlex.quote(str(launch_script_path))}"

    def build_launch_script(self, task: CodingTask, prompt_path: Path, log_path: Path) -> str:
        """Build the full isolated shell wrapper written to the per-task launch script."""
        codex_args = self.build_codex_args(task)
        codex_cmd = " ".join(shlex.quote(part) for part in codex_args)
        inner = (
            f"cd {shlex.quote(task.repo_path)} && "
            f"{codex_cmd} < {shlex.quote(str(prompt_path))} 2>&1 | tee -a {shlex.quote(str(log_path))}"
        )
        return "#!/bin/sh\nexec " + self.build_shell_wrapper(inner) + "\n"

    def build_codex_args(self, task: CodingTask) -> list[str]:
        """Build the Codex CLI argv for one coding task."""
        args = [self.codex_bin, "exec", "--json", "--full-auto"]
        for override in _CODEX_CONFIG_OVERRIDES:
            args.extend(["-c", override])
        args.extend(["-C", task.repo_path, "-"])
        return args

    def build_shell_wrapper(self, command: str) -> str:
        """Wrap one command in an isolated minimal shell environment."""
        env_parts = " ".join(
            f"{key}={shlex.quote(value)}"
            for key, value in self.shell_env.items()
        )
        return f"/usr/bin/env -i {env_parts} {shlex.quote(self.shell_bin)} -c {shlex.quote(command)}"

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

    @staticmethod
    def summarize_startup_diagnostic(text: str) -> str:
        """Return a human-facing startup diagnostic for early pane failures."""
        lowered = text.lower()
        for patterns, summary in _STARTUP_DIAGNOSTICS:
            if all(pattern in lowered for pattern in patterns):
                return summary
        return ""

    def _write_prompt_file(self, task: CodingTask, prompt: str) -> Path:
        path = self.artifacts_dir / f"{task.id}.prompt.txt"
        path.write_text(prompt, encoding="utf-8")
        return path

    def _write_launch_script(self, task: CodingTask, prompt_path: Path, log_path: Path) -> Path:
        path = self.artifacts_dir / f"{task.id}.launch.sh"
        path.write_text(
            self.build_launch_script(task, prompt_path, log_path),
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def _log_path(self, task: CodingTask) -> Path:
        return self.artifacts_dir / f"{task.id}.codex.log"

    def _has_session(self, session: str) -> bool:
        result = self._run_tmux("has-session", "-t", session, check=False)
        return result.returncode == 0

    def _new_session(self, session: str, command: str) -> None:
        self._run_tmux("new-session", "-d", "-s", session, "-c", self.launch_cwd, command)

    def _respawn_session(self, session: str, command: str) -> None:
        self._run_tmux("respawn-pane", "-k", "-t", self._target(session), "-c", self.launch_cwd, command)

    def _send_ctrl_c(self, session: str) -> None:
        self._run_tmux("send-keys", "-t", self._target(session), "C-c")

    def _target(self, session: str) -> str:
        return f"{session}:0.0"

    def _build_shell_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in _WORKER_ENV_KEYS:
            if value := os.environ.get(key):
                env[key] = value
        env.setdefault("HOME", str(Path.home()))
        user = env.get("USER") or os.environ.get("USER") or "miau"
        env.setdefault("USER", user)
        env.setdefault("LOGNAME", user)
        env["TERM"] = "screen-256color"
        env["PATH"] = self._build_worker_path()
        env["SHELL"] = self.shell_bin
        return env

    def _build_worker_path(self) -> str:
        entries: list[str] = []
        for candidate in _DEFAULT_PATH_SEGMENTS:
            if candidate not in entries:
                entries.append(candidate)
        pnpm_path = str(Path.home() / "Library" / "pnpm")
        if pnpm_path not in entries:
            entries.append(pnpm_path)
        for segment in os.environ.get("PATH", "").split(":"):
            if segment and segment not in entries:
                entries.append(segment)
        return ":".join(entries)

    def _resolve_launch_cwd(self) -> str:
        workspace = str(self.workspace)
        if Path(workspace).exists():
            return workspace
        home = str(Path.home())
        if Path(home).exists():
            return home
        return "/"

    def _default_socket_path(self) -> str:
        return str(ensure_dir(self.workspace / "automation" / "coding") / "tmux.sock")

    @staticmethod
    def _resolve_codex_bin(requested: str) -> str:
        if requested != "codex":
            return requested
        if resolved := shutil.which("codex"):
            return resolved
        app_path = Path("/Applications/Codex.app/Contents/Resources/codex")
        if app_path.exists():
            return str(app_path)
        return requested

    def _run_tmux(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [self.tmux_bin]
        if self.socket_path:
            cmd.extend(["-S", self.socket_path])
        cmd.extend(args)
        return self.runner(cmd, check=check, capture_output=True, text=True)

    @staticmethod
    def _default_runner(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, **kwargs)
