# Contributing to nanobot

nanobot is intentionally small (~4,000 lines). Before contributing, read the code — the core is genuinely readable in an afternoon.

## Quick Start

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Run linter:

```bash
ruff check nanobot
```

## Project Layout

```
nanobot/
├── agent/          # Core loop, context builder, memory, skills, subagents
├── bus/            # Asyncio message queue (inbound/outbound)
├── channels/       # One file per platform + base.py ABC
├── cli/            # Typer commands (onboard, agent, gateway, cron, status)
├── config/         # Pydantic settings + schema
├── cron/           # Scheduled task service
├── heartbeat/      # Periodic wake-up service
├── providers/      # LLM provider registry + per-provider classes
├── session/        # JSONL conversation history
├── skills/         # Built-in skill markdown files
└── utils/          # Helpers (file safety, logging)
bridge/             # Node.js WhatsApp bridge (separate npm project)
tests/              # pytest suite
```

---

## Adding a Channel

Channels live in `nanobot/channels/`. Each one is a single file that:

1. Subclasses `BaseChannel` from `nanobot.channels.base`
2. Implements `start()`, `stop()`, and `send()`
3. Calls `self._handle_message(...)` when an inbound message arrives

### Minimal skeleton

```python
# nanobot/channels/myplatform.py
from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage


class MyPlatformChannel(BaseChannel):
    name = "myplatform"

    async def start(self) -> None:
        self._running = True
        # connect to platform, start polling / long-poll / websocket …
        async for event in self._poll():
            await self._handle_message(
                sender_id=event.user_id,
                chat_id=event.chat_id,
                content=event.text,
            )

    async def stop(self) -> None:
        self._running = False
        # clean up connections …

    async def send(self, msg: OutboundMessage) -> None:
        # send msg.content back to msg.chat_id …
        pass
```

### Wiring it up

**1. Add config schema** (`nanobot/config/schema.py`):

```python
class MyPlatformConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    allow_from: list[str] = []

class ChannelsConfig(BaseModel):
    ...
    myplatform: MyPlatformConfig = MyPlatformConfig()
```

**2. Register in ChannelManager** (`nanobot/channels/manager.py`):

```python
from nanobot.channels.myplatform import MyPlatformChannel

# inside _init_channels():
if cfg.channels.myplatform.enabled:
    ch = MyPlatformChannel(cfg.channels.myplatform, self.bus)
    self._channels.append(ch)
    self._warn_if_open("myplatform", cfg.channels.myplatform)
```

**3. Add optional dependency** (`pyproject.toml`):

```toml
[project.optional-dependencies]
myplatform = ["myplatform-sdk>=1.0,<2.0"]
```

### `_handle_message` parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `sender_id` | `str` | Platform user ID (checked against `allow_from`) |
| `chat_id` | `str` | Conversation/channel ID |
| `content` | `str` | Message text |
| `media` | `list[str] \| None` | Optional list of media URLs |
| `metadata` | `dict \| None` | Arbitrary channel-specific data |
| `session_key` | `str \| None` | Override the session key (e.g. for thread isolation) |

### Access control

`BaseChannel.is_allowed()` automatically enforces `allow_from`. An empty list allows everyone. You do **not** need to check this yourself; `_handle_message` does it for you.

`ChannelManager._warn_if_open()` emits a startup security warning when `allow_from` is empty — always call it after registering the channel.

---

## Adding a Built-in Tool

Tools live in `nanobot/agent/tools/`. Each tool:

1. Subclasses `Tool` from `nanobot.agent.tools.base`
2. Implements `name`, `description`, `parameters` (JSON Schema), and `execute(**kwargs)`

### Minimal skeleton

```python
# nanobot/agent/tools/mytool.py
from typing import Any
from nanobot.agent.tools.base import Tool


class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "The input text"},
            },
            "required": ["input"],
        }

    async def execute(self, input: str, **kwargs: Any) -> str:
        return f"Processed: {input}"
```

### Registering the tool

In `nanobot/agent/tools/__init__.py` (or wherever tools are assembled), add:

```python
from nanobot.agent.tools.mytool import MyTool

registry.register(MyTool())
```

### Guidelines

- Return a plain `str` — the agent loop passes it back to the LLM as a tool result.
- On error, return a human-readable error string rather than raising.
- Respect `restrictToWorkspace` if your tool touches the filesystem — use the helpers in `nanobot.utils.helpers`.
- Keep `execute()` async; use `asyncio.to_thread()` for blocking I/O.

---

## Adding a Provider

LLM providers are driven by a metadata registry. Adding a new provider takes **two files**.

### Step 1: `nanobot/providers/registry.py`

Add a `ProviderSpec` entry to the `PROVIDERS` list:

```python
ProviderSpec(
    name="myprovider",                    # config key in config.json
    keywords=("myprovider", "mymodel"),   # model-string keywords for auto-detection
    env_key="MYPROVIDER_API_KEY",         # env var LiteLLM reads
    display_name="My Provider",           # shown in `nanobot status`
    litellm_prefix="myprovider",          # prefix added to model names
    skip_prefixes=("myprovider/",),       # avoid double-prefixing
)
```

Common optional fields:

| Field | Purpose |
|-------|---------|
| `env_extras` | Additional env vars: `(("EXTRA_VAR", "{api_key}"),)` |
| `model_overrides` | Per-model parameter overrides |
| `is_gateway` | `True` if this provider can route any model (like OpenRouter) |
| `detect_by_key_prefix` | API key prefix for auto-detection, e.g. `"sk-or-"` |
| `strip_model_prefix` | Strip an existing prefix before re-prefixing |

### Step 2: `nanobot/config/schema.py`

Add a field to `ProvidersConfig`:

```python
class ProvidersConfig(BaseModel):
    ...
    myprovider: ProviderConfig = ProviderConfig()
```

That's it. The provider will appear in `nanobot status`, accept `apiKey` / `apiBase` from config, and be available for model auto-detection.

### OAuth providers

For providers using OAuth (like `openai_codex`, `github_copilot`):

1. Subclass `OAuthProvider` in `nanobot/providers/`
2. Implement `login()` and token refresh
3. Register with `oauth=True` in `ProviderSpec`

---

## Writing a Skill

Skills are Markdown files that teach the agent how to use specific tools or perform specific workflows. They live in:

- `nanobot/skills/<name>/SKILL.md` — built-in skills shipped with nanobot
- `~/.nanobot/workspace/skills/<name>/SKILL.md` — user workspace skills (highest priority, override built-ins)

### Frontmatter schema

Every `SKILL.md` starts with a YAML frontmatter block:

```markdown
---
name: my-skill
description: "One-line description shown in the skills list."
metadata: {"nanobot":{"emoji":"🔧","always":false,"requires":{"bins":["mytool"],"env":["MY_API_KEY"]}}}
---

# My Skill

Teach the agent what to do here…
```

| Frontmatter field | Required | Description |
|-------------------|----------|-------------|
| `name` | Yes | Skill identifier (matches directory name) |
| `description` | Yes | Shown in the skills summary injected into the system prompt |
| `metadata` | No | JSON object with `nanobot` key (see below) |

#### `nanobot` metadata fields

| Field | Type | Description |
|-------|------|-------------|
| `always` | bool | If `true`, skill content is **always** loaded into the system prompt automatically |
| `emoji` | string | Emoji shown next to the skill in listings |
| `requires.bins` | `string[]` | CLI binaries that must be on `PATH` for this skill to be available |
| `requires.env` | `string[]` | Environment variables that must be set for this skill to be available |
| `install` | array | Install hints shown to the user when requirements are missing |

### Loading behaviour

1. On startup, `SkillsLoader.build_skills_summary()` generates an XML summary of all skills (name, description, availability) and injects it into the system prompt.
2. Skills with `always: true` have their **full content** loaded at startup.
3. For on-demand skills, the agent reads the full `SKILL.md` via `read_file` when it needs the detail.
4. Workspace skills override built-in skills with the same name.
5. Skills with unmet `requires` show as `available="false"` with a reason; the agent won't try to use them.

### Skill content guidelines

- Write in the imperative — explain **what to do**, not what the skill is.
- Include concrete command examples with expected output.
- Keep it concise — the agent reads the full file on demand, so avoid padding.
- Use `## Section` headers to organise multiple workflows within one skill.

---

## Tests

Tests are in `tests/`. Run with:

```bash
pytest                    # all tests
pytest tests/test_loop.py # single file
pytest -x                 # stop on first failure
```

Key test files:

| File | What it covers |
|------|---------------|
| `tests/test_loop.py` | Agent loop, tool dispatch, /stop, /new |
| `tests/test_memory.py` | Memory consolidation |
| `tests/test_session.py` | JSONL session load/save |
| `tests/test_channels.py` | Channel access control |
| `tests/test_heartbeat.py` | Heartbeat two-phase decision |
| `tests/test_mcp.py` | MCP tool wrapper |
| `tests/test_providers.py` | Provider registry |

When adding a channel, tool, or provider, add a corresponding test file.

---

## Code Style

- **Python ≥ 3.11**, async-first.
- `ruff` for linting (`ruff check nanobot`). Config in `pyproject.toml`.
- Type annotations on all public functions and class attributes.
- Docstrings on public classes and non-trivial methods.
- No magic numbers without a named constant and a comment explaining the value.

## Submitting a PR

1. Fork, branch from `main`.
2. Run `pytest` and `ruff check nanobot` — both must pass.
3. Keep PRs focused: one feature or fix per PR.
4. Update `README.md` if you add a new channel, provider, or user-visible feature.
5. Reference any related issue in the PR description.
