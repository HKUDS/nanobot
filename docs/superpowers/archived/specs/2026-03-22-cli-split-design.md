# CLI Split: Decompose commands.py into Focused Sub-Modules

**Date:** 2026-03-22
**Status:** Draft
**Scope:** Split `nanobot/cli/commands.py` (2582 lines) into 8 focused modules,
extract a shared `_make_agent_loop()` factory, and make `commands.py` a thin
assembly file.

## Problem

`nanobot/cli/commands.py` is the last remaining monolith in the codebase at
2582 lines. It contains 8 logically separate sub-apps, shared helpers, and
TTY/input utilities — all in one file. The AgentLoop setup pattern is
duplicated 5 times across `gateway`, `ui`, `agent`, `cron run`, and
`routing replay`.

## Solution

Convert `nanobot/cli/` into a proper package with one module per sub-app.

### New Package Structure

```
nanobot/cli/
├── __init__.py          # exports CliProgressHandler + app (updated)
├── commands.py          # thin assembly (~80 lines): creates app, imports
│                        #   sub-modules, registers sub-apps, top-level cmds
├── _shared.py           # shared factories + utilities (~150 lines)
├── progress.py          # CliProgressHandler (unchanged, already exists)
├── gateway.py           # gateway + ui commands (~360 lines)
├── agent.py             # agent command + TTY/input helpers (~400 lines)
├── memory.py            # memory_app (14 commands, ~690 lines)
├── routing.py           # routing_app + replay-deadletters (~450 lines)
├── cron.py              # cron_app (~230 lines)
├── channels.py          # channels_app (~130 lines)
└── provider.py          # provider_app (~96 lines)
```

### `_shared.py` — Shared Factories (~150 lines)

Extracted from `commands.py`, used across multiple sub-modules:

```python
# Module-level singletons
console = Console()

# Factories
def _make_provider(config: Config) -> LLMProvider: ...
def _make_agent_config(config: Config) -> AgentConfig: ...
def _make_agent_loop(config: Config, **overrides) -> AgentLoop: ...  # NEW
def _configure_log_sink(config: Config, logger) -> None: ...
def _print_agent_response(response: str, render_markdown: bool) -> None: ...
```

**`_make_agent_loop()` — the new factory.** Replaces 5 duplicated setup blocks:

```python
def _make_agent_loop(
    config: Config,
    *,
    bus: MessageBus | None = None,
    cron_service: CronService | None = None,
    session_manager: SessionManager | None = None,
) -> AgentLoop:
    """Construct an AgentLoop with standard wiring.

    Creates provider, bus, agent config, and wires observability.
    Callers can override bus, cron_service, and session_manager.
    """
    provider = _make_provider(config)
    if bus is None:
        bus = MessageBus()
    return AgentLoop(
        bus=bus,
        provider=provider,
        config=_make_agent_config(config),
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron_service,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        routing_config=config.agents.routing,
    )
```

Each command goes from ~20 lines of setup to:
```python
loop = _make_agent_loop(config, bus=bus, cron_service=cron)
```

### `commands.py` — Thin Assembly (~80 lines)

After the split, `commands.py` becomes:

```python
"""CLI entry point — assembles sub-apps into the root typer application."""
from __future__ import annotations
import typer
from nanobot import __version__

app = typer.Typer(name="nanobot", ...)

# Register sub-apps
from nanobot.cli.channels import channels_app
from nanobot.cli.cron import cron_app
from nanobot.cli.routing import routing_app
from nanobot.cli.memory import memory_app
from nanobot.cli.provider import provider_app

app.add_typer(channels_app, name="channels")
app.add_typer(cron_app, name="cron")
app.add_typer(routing_app, name="routing")
app.add_typer(memory_app, name="memory")
app.add_typer(provider_app, name="provider")

# Top-level commands
from nanobot.cli.gateway import gateway, ui
from nanobot.cli.agent import agent
from nanobot.cli._shared import onboard, status, version_callback

app.command()(gateway)
app.command()(ui)
app.command()(agent)
app.command()(onboard)
app.command()(status)
app.callback()(main)
```

**All tests that import `app` from `nanobot.cli.commands` continue to work
unchanged.** The public import path is preserved.

### Module Assignments

| Module | What moves there | Lines (est.) |
|--------|-----------------|-------------|
| `_shared.py` | `console`, `_make_provider`, `_make_agent_config`, `_make_agent_loop` (new), `_configure_log_sink`, `_print_agent_response`, `_sys_stderr`, `onboard`, `_create_workspace_templates`, `status` | ~150 |
| `gateway.py` | `gateway` command, `ui` command | ~360 |
| `agent.py` | `agent` command, `_PROMPT_SESSION`, `_flush_pending_tty_input`, `_restore_terminal`, `_init_prompt_session`, `_read_interactive_input_async`, `_drain_pending_tasks`, `_is_exit_command`, `EXIT_COMMANDS` | ~400 |
| `memory.py` | `memory_app`, `_memory_rollout_overrides`, all 13 memory commands | ~690 |
| `routing.py` | `routing_app`, all 4 routing commands, `replay_deadletters` | ~450 |
| `cron.py` | `cron_app`, all 5 cron commands | ~230 |
| `channels.py` | `channels_app`, `_get_bridge_dir`, `status`, `login` | ~130 |
| `provider.py` | `provider_app`, `_LOGIN_HANDLERS`, `_register_login`, `login`, OAuth handlers | ~96 |
| `commands.py` | Assembly only — imports + registration | ~80 |

### What Changes in Tests

**`app` imports continue to work** — all test files that do
`from nanobot.cli.commands import app` are unaffected.

**String-path `monkeypatch.setattr` calls must be updated.** These patch
symbols by dotted path — after the split, the symbols live in new modules.
If not updated, patches silently no-op and tests pass for the wrong reason.

| Test file | Patched symbol | Old path | New path |
|-----------|---------------|----------|----------|
| `test_commands_extended.py` | `_make_provider` | `nanobot.cli.commands._make_provider` | `nanobot.cli._shared._make_provider` |
| `test_commands_extended.py` | `_get_bridge_dir` | `nanobot.cli.commands._get_bridge_dir` | `nanobot.cli.channels._get_bridge_dir` |
| `test_commands_gateway_agent.py` | `_make_provider` (3 uses) | `nanobot.cli.commands._make_provider` | `nanobot.cli._shared._make_provider` |
| `test_commands_gateway_agent.py` | `_init_prompt_session` | `nanobot.cli.commands._init_prompt_session` | `nanobot.cli.agent._init_prompt_session` |
| `test_commands_gateway_agent.py` | `_flush_pending_tty_input` | `nanobot.cli.commands._flush_pending_tty_input` | `nanobot.cli.agent._flush_pending_tty_input` |
| `test_commands_gateway_agent.py` | `_restore_terminal` | `nanobot.cli.commands._restore_terminal` | `nanobot.cli.agent._restore_terminal` |
| `test_commands_gateway_agent.py` | `_read_interactive_input_async` | `nanobot.cli.commands._read_interactive_input_async` | `nanobot.cli.agent._read_interactive_input_async` |
| `test_commands_routing_cron.py` | `_make_provider` | `nanobot.cli.commands._make_provider` | `nanobot.cli._shared._make_provider` |
| `test_commands_channels_login.py` | `_get_bridge_dir` | `nanobot.cli.commands._get_bridge_dir` | `nanobot.cli.channels._get_bridge_dir` |
| `test_cli_input.py` | `_PROMPT_SESSION`, `PromptSession` | `nanobot.cli.commands.*` | `nanobot.cli.agent.*` |

**IMPORTANT:** The patch path must match where the symbol is **looked up at
runtime**, not where it's defined. If `gateway.py` does
`from nanobot.cli._shared import _make_provider` and a test patches
`nanobot.cli._shared._make_provider`, it works. But if the test patches
`nanobot.cli.gateway._make_provider`, it also works (patches the local
binding). Prefer patching at the source module (`_shared`) for consistency.

### `__init__.py` Update

```python
"""CLI module for nanobot."""
from __future__ import annotations
from nanobot.cli.progress import CliProgressHandler
from nanobot.cli.commands import app

__all__ = ["CliProgressHandler", "app"]
```

## Execution Order

1. **Create `_shared.py`** — extract shared factories + utilities
2. **Create `gateway.py`** — extract gateway + ui commands
3. **Create `agent.py`** — extract agent command + TTY helpers
4. **Create `memory.py`** — extract memory_app (largest sub-app)
5. **Create `routing.py`** — extract routing_app + replay-deadletters
6. **Create `cron.py`** — extract cron_app
7. **Create `channels.py`** — extract channels_app
8. **Create `provider.py`** — extract provider_app
9. **Slim `commands.py`** — reduce to assembly file
10. **Update test imports** — fix `test_commands_extended.py`
11. **Update `__init__.py`** — add `app` export
12. **Final validation** — `make check`

## Testing Strategy

- All existing tests pass unchanged (they import `app` from `commands.py`)
- `test_commands_extended.py` updated for direct imports from new modules
- No new tests needed — this is a pure structural refactoring
- `make check` validates everything

## Expected Result

| File | Before | After |
|------|--------|-------|
| `commands.py` | 2582 lines | ~80 lines (assembly) |
| `_shared.py` | — | ~150 lines |
| `gateway.py` | — | ~360 lines |
| `agent.py` | — | ~400 lines |
| `memory.py` | — | ~690 lines |
| `routing.py` | — | ~450 lines |
| `cron.py` | — | ~230 lines |
| `channels.py` | — | ~130 lines |
| `provider.py` | — | ~96 lines |

No single CLI file exceeds 700 lines. The duplicated AgentLoop setup
(5x ~20 lines) is replaced by a shared factory.

## Out of Scope

- Adding new tests for CLI commands (coverage improvement is a separate effort)
- Refactoring memory_app internals (690 lines, but cohesive — all memory commands)
- Changing CLI behavior or command signatures
- Modifying the `progress.py` module (already clean)
