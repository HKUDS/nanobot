# Contributing to Nanobot

## Quick Start

```bash
git clone https://github.com/your-org/nanobot.git
cd nanobot
make install       # Install dev dependencies
make check         # Verify everything works: lint + typecheck + test
```

## Project Structure

```
nanobot/
├── agent/          # Core engine: loop, context, streaming, tools/, memory/
├── channels/       # Chat platforms (Telegram, Discord, Slack, WhatsApp, Email, Web)
├── providers/      # LLM provider abstraction (100+ models via litellm)
├── bus/            # Async message bus (channel↔agent decoupling)
├── config/         # Pydantic config models + loader with migration
├── session/        # Conversation session management
├── cron/           # Scheduled task service
├── heartbeat/      # Periodic task execution (reads HEARTBEAT.md)
├── skills/         # Built-in skills (weather, github, summarize, ...)
├── cli/            # Typer CLI (onboard, agent, gateway, memory, cron)
├── errors.py       # Structured error taxonomy (NanobotError hierarchy)
└── utils/          # Path helpers, filename sanitization
```

> For detailed module ownership, file-level descriptions, and import rules, see
> [docs/architecture.md](../docs/architecture.md).

## Development Workflow

1. **Branch**: Create a feature branch from `main`
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Develop**: Make your changes, then validate:
   ```bash
   make lint          # Check linting
   make typecheck     # Check types
   make test          # Run tests
   # Or all at once:
   make check
   ```

3. **Commit**: Write clear commit messages
   ```
   feat: add weather forecast caching
   fix: handle empty tool response in registry
   refactor: extract token counting from context builder
   ```

4. **Push**: Run `make pre-push` before pushing (CI + merge-readiness check)

## Coding Conventions

### Module Header

Every Python module starts with:

```python
"""Module-level docstring describing purpose."""

from __future__ import annotations
```

### Type Hints

Type hints are required on all function signatures and class attributes:

```python
def process_message(self, text: str, *, channel: str | None = None) -> ToolResult:
    ...
```

Use `|` union syntax (Python 3.10+), not `Union[X, Y]`.

### Imports

Group imports: stdlib → third-party → local. Enforced by ruff `I` rules.

```python
import json                          # stdlib
from pathlib import Path

from loguru import logger            # third-party
from pydantic import BaseModel

from nanobot.errors import ToolExecutionError  # local
```

### `__all__` Exports

Every `__init__.py` must define `__all__` listing all public exports:

```python
__all__ = ["MemoryStore", "MemoryExtractor"]
```

### Tool Results

Tools always return structured results, never bare strings:

```python
return ToolResult.ok(output)
return ToolResult.fail(error_message, error_type="validation")
```

### Error Handling

Use typed exceptions from `nanobot/errors.py`:

```python
from nanobot.errors import ToolExecutionError, ProviderError

raise ToolExecutionError("file not found", tool_name="read_file", error_type="not_found")
```

Never catch bare `Exception` — use the specific error type.

## Testing

### Running Tests

```bash
make test           # Fast: stop on first failure (-x -q)
make test-verbose   # Verbose output
make test-cov       # With coverage report (85% gate)
make memory-eval    # Deterministic memory retrieval benchmark
make live-eval      # Run live agent evaluation
```

### Writing Tests

Use pytest-asyncio (auto mode — no `@pytest.mark.asyncio` decorator needed):

```python
async def test_tool_execution(tmp_path: Path):
    tool = ReadFileTool(working_dir=str(tmp_path))
    result = await tool.execute(path="test.txt")
    assert result.success
```

For LLM-dependent tests, use `ScriptedProvider` for deterministic behavior:

```python
from tests.test_agent_loop import ScriptedProvider, _make_loop

async def test_agent_responds(tmp_path: Path):
    provider = ScriptedProvider([LLMResponse(content="Hello!")])
    loop = _make_loop(tmp_path, provider)
    answer, _, _ = await loop._run_agent_loop([{"role": "user", "content": "Hi"}])
    assert answer == "Hello!"
```

Use `@pytest.mark.parametrize` for variant coverage:

```python
@pytest.mark.parametrize("cmd", ["rm -rf /", "format C:", "dd if=/dev/zero of=/dev/sda"])
def test_blocks_dangerous(tool, cmd):
    assert tool._guard_command(cmd, "/tmp") is not None
```

## Adding a New Tool

1. Create a new class in `nanobot/agent/tools/` extending `Tool`:

   ```python
   from nanobot.agent.tools.base import Tool, ToolResult

   class MyTool(Tool):
       name = "my_tool"
       description = "Does something useful"
       parameters = {
           "type": "object",
           "properties": {
               "input": {"type": "string", "description": "The input to process"},
           },
           "required": ["input"],
       }

       async def execute(self, **kwargs) -> ToolResult:
           input_val = kwargs["input"]
           # ... do work ...
           return ToolResult.ok(f"Processed: {input_val}")
   ```

2. Register in `AgentLoop.__init__` (`nanobot/agent/loop.py`):
   ```python
   self.registry.register(MyTool())
   ```

3. Reference: `ReadFileTool` in `nanobot/agent/tools/filesystem.py`

## Adding a New Skill

1. Create `nanobot/skills/your-skill/SKILL.md`:
   ```yaml
   ---
   name: your-skill
   description: What this skill does
   tools: [tool_name]      # optional: custom tools from tools.py
   ---
   # Your Skill

   Instructions for the agent on how to use this skill...
   ```

2. Optionally add `nanobot/skills/your-skill/tools.py` with `Tool` subclasses

3. Skills are auto-discovered by `SkillsLoader` in `nanobot/agent/skills.py`

4. Template: `nanobot/skills/weather/`

## Adding a New Channel

1. Subclass `BaseChannel` in `nanobot/channels/base.py`
2. Implement `start()`, `stop()`, `send_message()` methods
3. Register in `ChannelManager` (`nanobot/channels/manager.py`)
4. Reference: `nanobot/channels/telegram.py` or `nanobot/channels/discord.py`

## Memory System

The memory system uses a **mem0-first strategy** with local fallback:

- **MemoryStore** (`memory/store.py`): Primary API — handles retrieval, consolidation, persistence
- **Events** (`memory/persistence.py`): Append-only `events.jsonl` + `profile.json` + `MEMORY.md` snapshot
- **Extraction** (`memory/extractor.py`): LLM-based structured event extraction from conversations
- **Retrieval** (`memory/retrieval.py`): Local keyword fallback when mem0 vector store is unavailable
- **Re-ranking** (`memory/reranker.py`): Optional cross-encoder stage for improved relevance

**Important**: Never modify `case/memory_eval_cases.json` or `case/memory_eval_baseline.json` without running `make memory-eval` to verify metrics still pass.

## Security Rules

- **API keys**: Never hardcode. Use `~/.nanobot/config.json` with 0600 permissions.
- **Shell execution**: All commands pass through `_guard_command()` in `nanobot/agent/tools/shell.py` — deny patterns block destructive commands, optional allowlist mode restricts to safe commands only.
- **Filesystem**: Path traversal protection validates all paths against the workspace root.
- **Network**: Internal bridges bind to localhost only.

## PR Workflow

All changes follow a PR-first workflow. No direct pushes to `main`.

### For features and bug fixes

1. **Create an issue** (or reference an existing one) describing the goal.
2. **Branch** from `main`: `git checkout -b feature/short-description`
3. **Implement** the change. Run `make check` after every edit.
4. **Commit** with a clear message: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`.
5. **Push**: Run `make pre-push` to validate CI + merge-readiness, then push and open a PR.
6. **CI must pass** — lint, typecheck, import-check, prompt-check, and tests.
7. **Review** — request Copilot review + human review for non-trivial changes.
8. **Merge** only after all checks pass.

### For refactors

1. Write or update the relevant **ADR** (`docs/adr/`) before making code changes.
2. Follow `docs/refactoring-principles.md` — one extraction per PR, tests first.
3. Keep PRs under 500 lines of changed code. Split larger refactors.
4. Verify behavior is preserved: existing tests pass without logic changes.

### Architecture resources

- Module ownership and import rules: `docs/architecture.md`
- Architecture Decision Records: `docs/adr/`
- Refactoring guidelines: `docs/refactoring-principles.md`
- Reusable Copilot prompts: `.github/prompts/`
