# PROJECT KNOWLEDGE BASE

**Generated:** 2026-04-14
**Commit:** 13e2cfa
**Branch:** poc/cave-agent-runtime

## OVERVIEW

Ultra-lightweight personal AI agent. Python 3.11+ with hatch build, 12+ chat channel integrations, multi-LLM provider support. Includes a TypeScript WhatsApp bridge.

## STRUCTURE

```
nanobot/
├── agent/          # Core: loop.py (LLM↔tool), context.py (prompts), tools/
├── channels/       # 12 integrations (telegram, discord, whatsapp, feishu, etc.)
├── providers/      # LLM providers with registry pattern (openrouter, anthropic, openai, etc.)
├── config/         # Pydantic v2 config schema
├── cli/            # Typer CLI commands
├── skills/         # Bundled markdown+python skill packs
├── bus/            # Async message bus (inbound/outbound)
├── session/        # Conversation session persistence
├── cron/           # Scheduled tasks
├── heartbeat/      # Periodic proactive wake-up
├── templates/      # Jinja2 prompt templates
├── utils/          # Shared helpers
bridge/             # Separate TypeScript WhatsApp bridge (bundled into wheel)
tests/              # pytest + pytest-asyncio, organized by module
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add a tool | `nanobot/agent/tools/` | Subclass `Tool`, use `@tool_parameters` decorator, register in `loop.py:_register_default_tools()` |
| Add a provider | `nanobot/providers/registry.py` + `config/schema.py` | 2 steps: add `ProviderSpec` + add `ProvidersConfig` field |
| Add a channel | `nanobot/channels/` | Subclass `ChannelBase`, register in registry |
| Modify agent loop | `nanobot/agent/loop.py` | Core LLM↔tool execution engine |
| Modify prompts | `nanobot/agent/context.py` + `nanobot/templates/` | System prompt assembly + Jinja2 templates |
| Config schema | `nanobot/config/schema.py` | Pydantic v2 models, camelCase alias |
| CLI commands | `nanobot/cli/commands.py` | Typer app, 3 AgentLoop() construction sites |

## CONVENTIONS

- **Linting**: ruff (E,F,I,N,W rules), line-length 100, E501 ignored
- **Testing**: pytest with `asyncio_mode = "auto"`, fixtures defined locally (no conftest.py), `ScriptedProvider` pattern for mocking LLMs
- **Config**: Pydantic v2 with `to_camel` alias generator, accepts both camelCase and snake_case
- **Async**: All tool `execute()` methods are async. IPyKernel operations use `await`
- **Imports**: Lazy/conditional imports for optional deps (cave-agent, ipykernel)

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER** use `read_file` to send files to users — use `message` tool with `media` parameter
- **NEVER** write reminders to MEMORY.md for notifications — use `cron` tool
- **NEVER** commit API keys — use `${ENV_VAR}` interpolation in config.json
- Empty `allowFrom` denies all access since v0.1.4.post4 — use `["*"]` to allow everyone
- Type error suppression (`as any`, `@ts-ignore`) forbidden in bridge TypeScript
- Shell exec blocks dangerous patterns (`rm -rf /`, fork bombs, raw disk writes)

## COMMANDS

```bash
pip install -e .                    # Install from source
pytest tests/                       # Run tests
ruff check nanobot/                 # Lint
nanobot onboard                     # Initialize config
nanobot gateway                     # Start 24/7 gateway
nanobot agent                       # CLI chat
nanobot serve                       # OpenAI-compatible API
```

## NOTES

- `bridge/` is a separate TypeScript project bundled into the Python wheel via `force-include` in pyproject.toml
- Docker requires `SYS_ADMIN` capability for bubblewrap sandbox (Linux only)
- CI runs partial ruff lint (F401,F841 only), not full E,F,I,N,W ruleset
- AgentLoop has 3 construction sites in `commands.py` — all must be updated when adding params
- `core_agent_lines.sh` tracks "core runtime" line count (project philosophy: minimal code)
- Session checkpoint system preserves in-flight tool state across crashes/restarts
