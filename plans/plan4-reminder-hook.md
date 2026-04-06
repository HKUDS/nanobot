## System Reminders (Anti-Drift Injection)

### The Problem

LLMs drift. In a 60-turn session, instructions from the system prompt gradually lose influence as they get pushed further from the model's attention window. By turn 40, the agent might start ignoring constraints it followed perfectly at turn 5: it stops using the preferred test runner, forgets it's supposed to ask before deleting files, or starts writing code in a style the user explicitly rejected earlier.

Claude Code handles this by periodically re-injecting "reminder" messages into the conversation — not full system prompt repeats, but targeted micro-reminders calibrated to what the agent is currently doing. The key insight is that reminders should be **contextual**, not just periodic. You don't remind the agent about testing conventions when it's writing documentation.

### The Implementation

```python
"""
System Reminders — anti-drift injection for nanobot.

Long agent sessions suffer from instruction drift: the model gradually
"forgets" system prompt rules as they recede in the context window.
This module injects targeted micro-reminders at strategic points to
keep the agent aligned with its instructions.

Two injection strategies:
  1. Periodic — every N turns, inject a baseline reminder
  2. Contextual — detect what the agent is doing and inject relevant rules

Reminders are injected as lightweight system messages, not full prompt
repeats. They're designed to be ~50-150 tokens each — cheap enough to
inject frequently without eating the context budget.

Usage:
    reminders = ReminderEngine(config)
    reminders.register("file_safety", trigger=triggers.before_write,
                        message="Always ask before deleting or overwriting files.")

    # In the agent loop:
    injections = reminders.check(turn_number, last_assistant_msg, pending_tool)
    for msg in injections:
        compactor.push("system", msg, protected=False)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional


# ── Types ────────────────────────────────────────────────────────────────

class TriggerType(Enum):
    PERIODIC = auto()          # fires every N turns
    TOOL_MATCH = auto()        # fires when a specific tool is about to be called
    CONTENT_MATCH = auto()     # fires when assistant output matches a pattern
    DRIFT_DETECTED = auto()    # fires when known drift signals appear
    BUDGET_PRESSURE = auto()   # fires when context is getting full
    MANUAL = auto()            # fired explicitly by hooks or user


@dataclass
class Reminder:
    """A single reminder rule."""
    name: str
    message: str
    trigger_type: TriggerType
    # Trigger configuration (meaning depends on trigger_type)
    trigger_value: str | int | None = None
    # Cooldown: minimum turns between firings of this reminder
    cooldown: int = 8
    # Priority: higher priority reminders survive budget cuts
    priority: int = 5
    # Track state
    last_fired_turn: int = -100
    fire_count: int = 0
    enabled: bool = True

    @property
    def token_estimate(self) -> int:
        return max(1, int(len(self.message) / 3.5))


@dataclass
class ReminderConfig:
    """Global configuration for the reminder engine."""
    # Base periodic interval (inject a general reminder every N turns)
    periodic_interval: int = 12
    # After this many turns, shorten the interval (agent is more likely to drift)
    accelerated_after: int = 30
    accelerated_interval: int = 8
    # Max total reminder tokens injected per check
    max_injection_tokens: int = 400
    # Enable/disable contextual triggers
    contextual_enabled: bool = True


# ── Built-in drift detectors ────────────────────────────────────────────

class DriftDetectors:
    """
    Pattern matchers that detect common drift behaviors.
    Each returns True if drift is detected in the assistant's last message.
    """

    @staticmethod
    def unauthorized_file_delete(text: str) -> bool:
        """Agent deleting files without asking."""
        patterns = [
            r"rm\s+-rf?\s+",
            r"os\.remove\(",
            r"shutil\.rmtree\(",
            r"I'(?:ve|ll)\s+(?:deleted?|removed?)\s+",
            r"unlink\(",
        ]
        return any(re.search(p, text, re.I) for p in patterns)

    @staticmethod
    def apology_loop(text: str) -> bool:
        """Agent stuck in apologize-retry loops."""
        apology_phrases = [
            "I apologize", "sorry about that", "my mistake",
            "let me try again", "I made an error",
        ]
        count = sum(1 for p in apology_phrases if p.lower() in text.lower())
        return count >= 2

    @staticmethod
    def scope_creep(text: str) -> bool:
        """Agent doing unrequested refactoring or changes."""
        patterns = [
            r"while I'?m at it",
            r"I(?:'ll| will) also (?:refactor|clean up|improve|update)",
            r"let me (?:also|additionally)",
            r"I noticed .+ could (?:also |)be (?:improved|refactored|cleaned)",
        ]
        return any(re.search(p, text, re.I) for p in patterns)

    @staticmethod
    def hallucinated_tool(text: str) -> bool:
        """Agent referencing tools that don't exist."""
        fake_tools = [
            "run_command", "execute_code", "search_web",
            "browse_url", "ask_user", "send_email",
        ]
        return any(tool in text for tool in fake_tools)

    @staticmethod
    def markdown_overuse(text: str) -> bool:
        """Agent producing excessive markdown in conversational context."""
        header_count = len(re.findall(r"^#{1,3}\s", text, re.M))
        return header_count > 4


# ── Reminder Engine ──────────────────────────────────────────────────────

class ReminderEngine:
    """
    Manages reminder rules and decides which to inject at each turn.

    The engine doesn't modify the conversation directly — it returns
    a list of message strings that the caller should inject.
    """

    def __init__(self, config: Optional[ReminderConfig] = None):
        self.config = config or ReminderConfig()
        self.reminders: dict[str, Reminder] = {}
        self.turn_count: int = 0
        self._register_defaults()

    # ── default reminders ────────────────────────────────────────────
    def _register_defaults(self) -> None:
        """Register the standard anti-drift reminders."""

        self.register(Reminder(
            name="tool_discipline",
            message=(
                "[Reminder] Use only the tools provided. Do not fabricate tool "
                "names or assume tools exist. If you need a capability you don't "
                "have, say so explicitly."
            ),
            trigger_type=TriggerType.PERIODIC,
            trigger_value=None,  # uses global periodic interval
            priority=9,
            cooldown=15,
        ))

        self.register(Reminder(
            name="file_safety",
            message=(
                "[Reminder] Before deleting, moving, or overwriting any file, "
                "confirm with the user. Never run destructive operations silently."
            ),
            trigger_type=TriggerType.DRIFT_DETECTED,
            trigger_value="unauthorized_file_delete",
            priority=10,
            cooldown=5,
        ))

        self.register(Reminder(
            name="stay_focused",
            message=(
                "[Reminder] Complete the current task before starting new ones. "
                "Do not refactor, rename, or restructure code the user didn't "
                "ask you to change."
            ),
            trigger_type=TriggerType.DRIFT_DETECTED,
            trigger_value="scope_creep",
            priority=8,
            cooldown=10,
        ))

        self.register(Reminder(
            name="break_apology_loop",
            message=(
                "[Reminder] If an approach isn't working after 2 attempts, stop "
                "and explain the blocker to the user instead of retrying the same "
                "strategy. Ask for guidance."
            ),
            trigger_type=TriggerType.DRIFT_DETECTED,
            trigger_value="apology_loop",
            priority=9,
            cooldown=6,
        ))

        self.register(Reminder(
            name="conciseness",
            message=(
                "[Reminder] Keep explanations concise. Show the code change, "
                "explain briefly why, move on. Don't repeat what the user already "
                "knows."
            ),
            trigger_type=TriggerType.PERIODIC,
            trigger_value=None,
            priority=4,
            cooldown=20,
        ))

        self.register(Reminder(
            name="budget_warning",
            message=(
                "[Reminder] Context window is getting full. Be more concise in "
                "responses. Summarize tool outputs instead of echoing them in full. "
                "Focus on completing the current task."
            ),
            trigger_type=TriggerType.BUDGET_PRESSURE,
            trigger_value=None,
            priority=10,
            cooldown=10,
        ))

    # ── registration ─────────────────────────────────────────────────
    def register(self, reminder: Reminder) -> None:
        self.reminders[reminder.name] = reminder

    def unregister(self, name: str) -> None:
        self.reminders.pop(name, None)

    def enable(self, name: str) -> None:
        if name in self.reminders:
            self.reminders[name].enabled = True

    def disable(self, name: str) -> None:
        if name in self.reminders:
            self.reminders[name].enabled = False

    # ── check & inject ───────────────────────────────────────────────
    def check(
        self,
        turn_number: int,
        last_assistant_msg: str = "",
        pending_tool: str = "",
        budget_utilization: float = 0.0,
    ) -> list[str]:
        """
        Evaluate all reminder rules against current state.
        Returns a list of reminder messages to inject (may be empty).

        Parameters
        ----------
        turn_number : int
            Current conversation turn index.
        last_assistant_msg : str
            The assistant's most recent message (for drift detection).
        pending_tool : str
            Name of the tool about to be called (for tool-match triggers).
        budget_utilization : float
            Context budget usage as a fraction (0.0 to 1.0).
        """
        self.turn_count = turn_number
        candidates: list[Reminder] = []

        for reminder in self.reminders.values():
            if not reminder.enabled:
                continue
            if (turn_number - reminder.last_fired_turn) < reminder.cooldown:
                continue

            fired = False

            if reminder.trigger_type == TriggerType.PERIODIC:
                interval = self._current_interval()
                if turn_number > 0 and turn_number % interval == 0:
                    fired = True

            elif reminder.trigger_type == TriggerType.TOOL_MATCH:
                if pending_tool and reminder.trigger_value:
                    if re.search(reminder.trigger_value, pending_tool, re.I):
                        fired = True

            elif reminder.trigger_type == TriggerType.CONTENT_MATCH:
                if reminder.trigger_value and last_assistant_msg:
                    if re.search(reminder.trigger_value, last_assistant_msg, re.I):
                        fired = True

            elif reminder.trigger_type == TriggerType.DRIFT_DETECTED:
                if last_assistant_msg and reminder.trigger_value:
                    detector = getattr(DriftDetectors, reminder.trigger_value, None)
                    if detector and detector(last_assistant_msg):
                        fired = True

            elif reminder.trigger_type == TriggerType.BUDGET_PRESSURE:
                if budget_utilization > 0.80:
                    fired = True

            if fired:
                candidates.append(reminder)

        # Sort by priority (highest first), then trim to token budget
        candidates.sort(key=lambda r: r.priority, reverse=True)
        selected: list[str] = []
        tokens_used = 0

        for reminder in candidates:
            if tokens_used + reminder.token_estimate > self.config.max_injection_tokens:
                continue
            selected.append(reminder.message)
            tokens_used += reminder.token_estimate
            reminder.last_fired_turn = turn_number
            reminder.fire_count += 1

        return selected

    def _current_interval(self) -> int:
        """Periodic interval shortens in longer sessions."""
        if self.turn_count >= self.config.accelerated_after:
            return self.config.accelerated_interval
        return self.config.periodic_interval

    # ── diagnostics ──────────────────────────────────────────────────
    def stats(self) -> dict:
        return {
            name: {
                "fire_count": r.fire_count,
                "last_fired": r.last_fired_turn,
                "enabled": r.enabled,
            }
            for name, r in self.reminders.items()
        }
```

### Why This Works

The core design decisions are worth calling out.

**Contextual over periodic.** Purely periodic reminders waste tokens. If the agent hasn't touched a file in 20 turns, reminding it about file safety is noise. The drift detectors act as tripwires — the `unauthorized_file_delete` detector fires only when the agent's output actually contains deletion patterns. This means reminders are injected precisely when they're needed, not on a dumb timer.

**Cooldowns prevent reminder spam.** Each reminder has its own cooldown period. The `file_safety` reminder has a tight cooldown of 5 turns because the consequences of drift there are severe. The `conciseness` reminder has a cooldown of 20 because it's low-stakes guidance. Without cooldowns, a persistent drift behavior would trigger the same reminder every single turn, eating the context budget.

**Accelerated intervals in long sessions.** After turn 30, the periodic interval shrinks from 12 to 8 turns. This matches empirically observed drift patterns — the model's adherence to system prompt instructions degrades roughly logarithmically with conversation length, so you need more frequent reinforcement later in the session.

**Token-budgeted injection.** Each `check()` call has a cap of 400 tokens for injections. If multiple reminders trigger simultaneously, they're ranked by priority and only the most important ones fit. The `file_safety` reminder (priority 10) will always beat the `conciseness` reminder (priority 4).

---

## Hooks (Custom Lifecycle Events)

### The Problem

Every project has unique conventions. One team wants ESLint to run after every file write. Another wants to auto-format Python with Black. Someone else needs to sync a lockfile whenever `package.json` changes. Claude Code handles this with a hooks system — user-defined callbacks that fire at specific points in the agent lifecycle. The agent itself doesn't need to know about these conventions; the hooks enforce them externally.

### The Implementation

```python
"""
Hooks — custom lifecycle event system for nanobot.

Hooks let users attach custom logic to specific points in the agent's
execution lifecycle. They're the primary extension mechanism: instead of
modifying agent internals, you register callbacks that fire at well-defined
points.

Lifecycle points:
  on_session_start      — agent session begins
  on_session_end        — agent session ends (cleanup, persistence)
  on_turn_start         — before processing a user message
  on_turn_end           — after the agent has responded
  on_tool_pre           — before a tool is executed (can block/modify)
  on_tool_post          — after a tool returns (can modify output)
  on_file_write         — after a file is written to disk
  on_file_read          — after a file is read (for audit logging)
  on_compact            — after context compaction occurs
  on_error              — when an error is caught
  on_reminder_injected  — after a system reminder fires
  on_memory_write       — after something is persisted to memory

Hook types:
  - Observer hooks: fire-and-forget, cannot modify the event
  - Filter hooks: can modify or block the event (return modified data or None to cancel)
  - Async hooks: run in background, don't block the agent loop

Usage:
    hooks = HookManager()

    @hooks.on("on_file_write")
    def auto_format(event):
        if event.data["path"].endswith(".py"):
            subprocess.run(["black", event.data["path"]])

    @hooks.on("on_tool_pre", hook_type=HookType.FILTER)
    def block_dangerous_commands(event):
        cmd = event.data.get("command", "")
        if "rm -rf" in cmd and "/" == cmd.split("rm -rf")[-1].strip()[0]:
            return None  # block the tool call
        return event.data  # allow it through

    # In the agent loop, the runner fires hooks:
    runner.hooks.fire("on_file_write", {"path": "src/main.py", "content": "..."})
"""

from __future__ import annotations

import inspect
import subprocess
import traceback
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Optional
import json
import time


# ── Types ────────────────────────────────────────────────────────────────

class HookType(Enum):
    OBSERVER = auto()    # fire-and-forget, no return value used
    FILTER = auto()      # can modify event data or return None to cancel
    ASYNC_BG = auto()    # runs in background thread (observer only)


class HookPoint(str, Enum):
    """Well-defined lifecycle points where hooks can attach."""
    SESSION_START     = "on_session_start"
    SESSION_END       = "on_session_end"
    TURN_START        = "on_turn_start"
    TURN_END          = "on_turn_end"
    TOOL_PRE          = "on_tool_pre"
    TOOL_POST         = "on_tool_post"
    FILE_WRITE        = "on_file_write"
    FILE_READ         = "on_file_read"
    COMPACT           = "on_compact"
    ERROR             = "on_error"
    REMINDER_INJECTED = "on_reminder_injected"
    MEMORY_WRITE      = "on_memory_write"


@dataclass
class HookEvent:
    """Payload passed to hook callbacks."""
    hook_point: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    session_turn: int = 0
    # For filter hooks, the caller checks this after firing
    cancelled: bool = False
    # Modified data (filter hooks can replace this)
    result_data: Optional[dict[str, Any]] = None


@dataclass
class RegisteredHook:
    """A single registered hook callback."""
    name: str
    hook_point: str
    callback: Callable[[HookEvent], Any]
    hook_type: HookType = HookType.OBSERVER
    priority: int = 5            # higher runs first
    enabled: bool = True
    # Optional: only fire for specific conditions
    condition: Optional[Callable[[HookEvent], bool]] = None
    # Stats
    invocation_count: int = 0
    total_time_ms: float = 0.0
    last_error: Optional[str] = None


# ── Shell command hooks (loaded from config) ─────────────────────────────

@dataclass
class ShellHookConfig:
    """
    Hooks defined in .nanobot/hooks.json — lets users define hooks
    as shell commands without writing Python.

    Example hooks.json:
    {
      "hooks": [
        {
          "name": "format_python",
          "on": "on_file_write",
          "command": "black {path}",
          "condition": "path.endswith('.py')",
          "timeout": 10
        },
        {
          "name": "lint_js",
          "on": "on_file_write",
          "command": "eslint --fix {path}",
          "condition": "path.endswith('.js') or path.endswith('.ts')",
          "timeout": 15
        },
        {
          "name": "run_tests_on_change",
          "on": "on_file_write",
          "command": "pytest {path} -x --tb=short",
          "condition": "path.startswith('tests/')",
          "timeout": 30
        }
      ]
    }
    """
    name: str
    on: str
    command: str
    condition: str = ""          # Python expression evaluated against event.data
    timeout: int = 10
    enabled: bool = True


# ── HookManager ──────────────────────────────────────────────────────────

class HookManager:
    """
    Central hook registry and dispatcher.

    Hooks can be registered via:
      1. Python decorator (@hooks.on)
      2. Python API (hooks.register)
      3. Shell commands in .nanobot/hooks.json (hooks.load_shell_hooks)
    """

    def __init__(self):
        self._hooks: dict[str, list[RegisteredHook]] = {
            hp.value: [] for hp in HookPoint
        }
        self._shell_hooks: list[ShellHookConfig] = []
        self._event_log: list[dict] = []
        self._max_log_size: int = 200

    # ── decorator registration ───────────────────────────────────────
    def on(
        self,
        hook_point: str,
        name: Optional[str] = None,
        hook_type: HookType = HookType.OBSERVER,
        priority: int = 5,
        condition: Optional[Callable[[HookEvent], bool]] = None,
    ):
        """Decorator to register a hook callback."""
        def decorator(fn: Callable[[HookEvent], Any]):
            hook_name = name or fn.__name__
            self.register(RegisteredHook(
                name=hook_name,
                hook_point=hook_point,
                callback=fn,
                hook_type=hook_type,
                priority=priority,
                condition=condition,
            ))
            return fn
        return decorator

    # ── API registration ─────────────────────────────────────────────
    def register(self, hook: RegisteredHook) -> None:
        point = hook.hook_point
        if point not in self._hooks:
            self._hooks[point] = []
        self._hooks[point].append(hook)
        # Keep sorted by priority (highest first)
        self._hooks[point].sort(key=lambda h: h.priority, reverse=True)

    def unregister(self, name: str) -> None:
        for point in self._hooks:
            self._hooks[point] = [h for h in self._hooks[point] if h.name != name]

    def enable(self, name: str) -> None:
        for hooks in self._hooks.values():
            for h in hooks:
                if h.name == name:
                    h.enabled = True

    def disable(self, name: str) -> None:
        for hooks in self._hooks.values():
            for h in hooks:
                if h.name == name:
                    h.enabled = False

    # ── shell hook loading ───────────────────────────────────────────
    def load_shell_hooks(self, workspace_path: str | Path) -> int:
        """
        Load hook definitions from .nanobot/hooks.json.
        Returns the number of hooks loaded.
        """
        hooks_file = Path(workspace_path) / ".nanobot" / "hooks.json"
        if not hooks_file.exists():
            return 0

        try:
            config = json.loads(hooks_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            self._log_event("shell_hook_load_error", {"error": str(e)})
            return 0

        loaded = 0
        for entry in config.get("hooks", []):
            try:
                shell_config = ShellHookConfig(**entry)
                self._shell_hooks.append(shell_config)
                # Wrap in a RegisteredHook
                self.register(RegisteredHook(
                    name=f"shell:{shell_config.name}",
                    hook_point=shell_config.on,
                    callback=self._make_shell_callback(shell_config),
                    hook_type=HookType.OBSERVER,
                    priority=3,  # shell hooks run after Python hooks
                    enabled=shell_config.enabled,
                ))
                loaded += 1
            except (TypeError, ValueError) as e:
                self._log_event("shell_hook_parse_error", {
                    "entry": entry, "error": str(e)
                })

        return loaded

    def _make_shell_callback(self, config: ShellHookConfig) -> Callable:
        """Create a callback that runs a shell command."""
        def callback(event: HookEvent) -> None:
            # Evaluate condition if present
            if config.condition:
                try:
                    if not eval(config.condition, {"__builtins__": {}}, event.data):
                        return
                except Exception:
                    return  # condition eval failed, skip silently

            # Template the command with event data
            try:
                cmd = config.command.format(**event.data)
            except KeyError:
                return  # missing template variable, skip

            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=config.timeout,
                    cwd=event.data.get("workspace", None),
                )
                if result.returncode != 0:
                    self._log_event("shell_hook_failed", {
                        "hook": config.name,
                        "command": cmd,
                        "returncode": result.returncode,
                        "stderr": result.stderr[:500],
                    })
            except subprocess.TimeoutExpired:
                self._log_event("shell_hook_timeout", {
                    "hook": config.name,
                    "command": cmd,
                    "timeout": config.timeout,
                })
            except OSError as e:
                self._log_event("shell_hook_error", {
                    "hook": config.name,
                    "error": str(e),
                })

        return callback

    # ── event firing ─────────────────────────────────────────────────
    def fire(
        self,
        hook_point: str,
        data: dict[str, Any],
        session_turn: int = 0,
    ) -> HookEvent:
        """
        Fire all hooks registered at the given lifecycle point.

        For FILTER hooks: if any filter returns None, the event is
        marked as cancelled. If it returns modified data, subsequent
        hooks (and the caller) see the modified version.

        Returns the HookEvent with final state (check .cancelled and
        .result_data).
        """
        event = HookEvent(
            hook_point=hook_point,
            data=data.copy(),
            session_turn=session_turn,
        )
        event.result_data = data.copy()

        hooks = self._hooks.get(hook_point, [])
        if not hooks:
            return event

        for hook in hooks:
            if not hook.enabled:
                continue

            # Check optional condition
            if hook.condition and not hook.condition(event):
                continue

            start = time.time()
            try:
                result = hook.callback(event)

                # Handle filter hooks
                if hook.hook_type == HookType.FILTER:
                    if result is None:
                        event.cancelled = True
                        self._log_event("hook_cancelled_event", {
                            "hook": hook.name,
                            "hook_point": hook_point,
                        })
                        break  # stop chain, event is cancelled
                    elif isinstance(result, dict):
                        event.data = result
                        event.result_data = result

            except Exception as e:
                hook.last_error = f"{type(e).__name__}: {e}"
                self._log_event("hook_error", {
                    "hook": hook.name,
                    "hook_point": hook_point,
                    "error": hook.last_error,
                    "traceback": traceback.format_exc()[:500],
                })
            finally:
                elapsed = (time.time() - start) * 1000
                hook.invocation_count += 1
                hook.total_time_ms += elapsed

        self._log_event("hook_fired", {
            "hook_point": hook_point,
            "hooks_run": sum(1 for h in hooks if h.enabled),
            "cancelled": event.cancelled,
        })

        return event

    # ── convenience fire methods ─────────────────────────────────────
    def fire_tool_pre(self, tool_name: str, tool_args: dict, **extra) -> HookEvent:
        """Fire on_tool_pre. Returns event — check .cancelled before executing."""
        return self.fire(HookPoint.TOOL_PRE.value, {
            "tool": tool_name,
            "args": tool_args,
            **extra,
        })

    def fire_tool_post(self, tool_name: str, tool_result: Any, **extra) -> HookEvent:
        return self.fire(HookPoint.TOOL_POST.value, {
            "tool": tool_name,
            "result": tool_result,
            **extra,
        })

    def fire_file_write(self, path: str, content: str, **extra) -> HookEvent:
        return self.fire(HookPoint.FILE_WRITE.value, {
            "path": path,
            "content": content,
            **extra,
        })

    # ── logging ──────────────────────────────────────────────────────
    def _log_event(self, event_type: str, data: dict) -> None:
        entry = {
            "type": event_type,
            "time": time.time(),
            **data,
        }
        self._event_log.append(entry)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]

    # ── diagnostics ──────────────────────────────────────────────────
    def stats(self) -> dict:
        all_hooks = []
        for hooks in self._hooks.values():
            for h in hooks:
                all_hooks.append({
                    "name": h.name,
                    "hook_point": h.hook_point,
                    "type": h.hook_type.name,
                    "enabled": h.enabled,
                    "invocations": h.invocation_count,
                    "avg_ms": (
                        round(h.total_time_ms / h.invocation_count, 2)
                        if h.invocation_count > 0 else 0
                    ),
                    "last_error": h.last_error,
                })
        return {
            "registered_hooks": len(all_hooks),
            "hooks": all_hooks,
            "recent_events": self._event_log[-10:],
        }

    def list_hooks(self, hook_point: Optional[str] = None) -> list[str]:
        """List registered hook names, optionally filtered by point."""
        if hook_point:
            return [h.name for h in self._hooks.get(hook_point, [])]
        return [
            h.name
            for hooks in self._hooks.values()
            for h in hooks
        ]
```

### How It All Wires Together

Here's the agent loop with all four systems integrated — memory, compaction, reminders, and hooks:

```python
"""
nanobot/agent/runner.py — main agent loop integrating all subsystems.
"""

from nanobot.agent.memory import MemoryStore
from nanobot.agent.compactor import ContextCompactor
from nanobot.agent.reminders import ReminderEngine, ReminderConfig
from nanobot.agent.hooks import HookManager, HookPoint


class AgentRunner:
    def __init__(self, workspace: str, llm, system_prompt: str):
        self.llm = llm
        self.workspace = workspace

        # 1. Persistent memory
        self.memory = MemoryStore(workspace)
        self.memory.bump_session_count()

        # 2. Context compactor (with LLM-backed summarizer)
        self.compactor = ContextCompactor(
            memory_store=self.memory,
            budget=120_000,
            summarizer=lambda instr, text: llm.complete(instr + text, max_tokens=300),
        )

        # 3. Anti-drift reminders
        self.reminders = ReminderEngine(ReminderConfig())

        # 4. Lifecycle hooks
        self.hooks = HookManager()
        self.hooks.load_shell_hooks(workspace)

        # Inject system prompt (protected from compaction)
        self.compactor.push("system", system_prompt, protected=True)
        self.turn = 0

    def run_turn(self, user_message: str) -> str:
        self.turn += 1

        # ── Hook: turn start ─────────────────────────────────────
        self.hooks.fire(HookPoint.TURN_START.value, {
            "turn": self.turn,
            "message": user_message,
        })

        # ── Push user message into context ───────────────────────
        self.compactor.push("user", user_message)

        # ── Check reminders before generating ────────────────────
        stats = self.compactor.stats()
        utilization = stats["tokens"]["total"] / stats["tokens"]["budget"]
        injections = self.reminders.check(
            turn_number=self.turn,
            last_assistant_msg="",       # no response yet
            pending_tool="",
            budget_utilization=utilization,
        )
        for reminder_msg in injections:
            self.compactor.push("system", reminder_msg)
            self.hooks.fire(HookPoint.REMINDER_INJECTED.value, {
                "message": reminder_msg,
                "turn": self.turn,
            })

        # ── Generate response ────────────────────────────────────
        context = self.compactor.render()
        response = self.llm.complete(context)

        # ── Post-generation drift check ──────────────────────────
        post_injections = self.reminders.check(
            turn_number=self.turn,
            last_assistant_msg=response,
            budget_utilization=utilization,
        )
        # If drift is detected, we could re-generate — but usually
        # we just inject the reminder for the NEXT turn.

        # ── Push response into context ───────────────────────────
        self.compactor.push("assistant", response)

        # ── Process any tool calls in the response ───────────────
        tool_calls = self._extract_tool_calls(response)
        for tool_name, tool_args in tool_calls:
            # Pre-hook: can block the call
            pre_event = self.hooks.fire_tool_pre(tool_name, tool_args)
            if pre_event.cancelled:
                self.compactor.push("system",
                    f"[Tool call '{tool_name}' was blocked by a hook.]")
                continue

            # Execute tool
            tool_result = self._execute_tool(tool_name, pre_event.result_data.get("args", tool_args))

            # Post-hook: can modify the result
            post_event = self.hooks.fire_tool_post(tool_name, tool_result)
            final_result = post_event.result_data.get("result", tool_result)

            self.compactor.push("tool", str(final_result))

            # File-write hook
            if tool_name in ("write_file", "edit_file"):
                path = tool_args.get("path", "")
                content = tool_args.get("content", "")
                self.hooks.fire_file_write(path, content, workspace=self.workspace)

        # ── Hook: turn end ───────────────────────────────────────
        self.hooks.fire(HookPoint.TURN_END.value, {
            "turn": self.turn,
            "response": response,
            "stats": self.compactor.stats(),
        })

        # ── Periodic memory consolidation ────────────────────────
        if self.memory.should_consolidate():
            self.memory.consolidate()

        return response

    def shutdown(self) -> None:
        """Clean up at end of session."""
        self.hooks.fire(HookPoint.SESSION_END.value, {
            "total_turns": self.turn,
            "memory_stats": self.memory.stats(),
            "compactor_stats": self.compactor.stats(),
            "hook_stats": self.hooks.stats(),
            "reminder_stats": self.reminders.stats(),
        })
        # Final memory persistence
        if self.memory.should_consolidate():
            self.memory.consolidate()

    def _extract_tool_calls(self, response: str) -> list[tuple[str, dict]]:
        """Parse tool calls from assistant response. Implementation varies by format."""
        # Placeholder — real implementation parses XML/JSON tool blocks
        return []

    def _execute_tool(self, name: str, args: dict):
        """Dispatch to actual tool implementations."""
        # Placeholder
        return f"Tool {name} executed."
```

### Design Rationale for Hooks

A few things worth highlighting about why the hook system is shaped this way.

**Observer vs. Filter distinction matters.** Most hooks are observers — they run after the fact and can't change what happened. Auto-formatting after a file write is an observer: the file was already written, the hook just cleans it up. But `on_tool_pre` is a filter hook: it runs before the tool executes and can return `None` to cancel the operation entirely. This is how you prevent the agent from running `rm -rf /` — a filter hook inspects the command and vetoes it. The two types have fundamentally different error semantics: a crashing observer is logged and ignored, but a crashing filter defaults to allowing the operation (fail-open) because blocking every tool call on a hook bug would brick the agent.

**Shell hooks exist because not everyone wants to write Python.** The `.nanobot/hooks.json` format lets a user define "run Black on every `.py` file write" without touching Python code. The config gets loaded at session start, each entry gets wrapped in a `RegisteredHook` with a subprocess callback, and they participate in the same priority/ordering system as native Python hooks. The condition field uses a deliberately restricted `eval` with no builtins — it's meant for simple expressions like `path.endswith('.py')`, not arbitrary code.

**Priority ordering is critical for filter chains.** When multiple filter hooks are registered at the same lifecycle point, they run in priority order. A security hook at priority 10 runs before a convenience hook at priority 3. If the security hook cancels the event, the convenience hook never sees it. This mimics middleware patterns in web frameworks — and for the same reasons.

**The event log provides observability.** Every hook firing, cancellation, and error is logged to an in-memory ring buffer. During development this is invaluable — you can inspect `hooks.stats()` to see which hooks are firing, how long they take, and which ones are failing. In Claude Code this kind of telemetry is what lets you diagnose "why did the agent skip that lint step" without having to reproduce the entire session.
