# nanobot — Codebase Guide

Ultra-lightweight personal AI assistant framework (~4k lines core agent code). Inspired by OpenClaw but 99% smaller. Python 3.11+, MIT license.

---

## Directory Map

```
nanobot/
├── agent/              # Core brain
│   ├── loop.py         # Main agent loop: receive msg → build context → call LLM → execute tools → respond
│   ├── context.py      # System prompt assembly (loads bootstrap files + memory + skills)
│   ├── memory.py       # Persistent memory: MEMORY.md (facts) + HISTORY.md (event log)
│   ├── skills.py       # Loads skill definitions from SKILL.md files
│   ├── subagent.py     # Background task runner via spawn tool
│   └── tools/
│       ├── base.py     # Abstract Tool class (name, description, parameters JSON schema, execute())
│       ├── registry.py # Tool registration, lookup, schema generation
│       ├── shell.py    # exec — run shell commands (with deny patterns)
│       ├── filesystem.py # read_file, write_file, edit_file, list_dir
│       ├── web.py      # web_search (Brave API), web_fetch
│       ├── message.py  # Send messages to users/channels
│       ├── spawn.py    # Spawn background subagents
│       ├── mcp.py      # MCP protocol client — auto-discovers and wraps external tools
│       └── cron.py     # Scheduled task management
├── channels/           # Chat platform integrations
│   ├── base.py         # BaseChannel interface (start, stop, send_message)
│   ├── manager.py      # Coordinates all active channels
│   ├── telegram.py     # Telegram (incl. voice transcription)
│   ├── discord.py      # Discord
│   ├── whatsapp.py     # WhatsApp (via bridge)
│   ├── slack.py        # Slack (Socket Mode)
│   ├── email.py        # Email (IMAP/SMTP)
│   ├── feishu.py       # Feishu/Lark
│   ├── dingtalk.py     # DingTalk
│   ├── mochat.py       # MoChat/Claw IM
│   └── qq.py           # QQ Bot
├── providers/          # LLM abstraction
│   ├── base.py         # LLMProvider interface (chat() → response)
│   ├── litellm_provider.py  # Multi-provider via LiteLLM (main path)
│   ├── custom_provider.py   # Direct OpenAI-compatible endpoint
│   ├── openai_codex_provider.py # OpenAI Codex (OAuth)
│   ├── registry.py     # ProviderSpec metadata — single source of truth for all providers
│   └── transcription.py # Voice → text (Groq Whisper)
├── config/
│   ├── schema.py       # Pydantic models for all config (agents, channels, providers, tools, gateway)
│   └── loader.py       # Load/save/migrate ~/.nanobot/config.json
├── session/
│   └── manager.py      # JSONL-based chat history per channel:chat_id
├── bus/
│   ├── queue.py        # MessageBus — async queues connecting channels ↔ agent
│   └── events.py       # InboundMessage, OutboundMessage dataclasses
├── cron/
│   ├── service.py      # CronService — scheduled job execution
│   └── types.py        # CronJob, CronSchedule data classes
├── heartbeat/
│   └── service.py      # Periodic wake-up (30min default), reads HEARTBEAT.md checklist
├── skills/             # 8 bundled skills (memory, github, weather, tmux, cron, summarize, clawhub, skill-creator)
├── templates/          # Bootstrap workspace files (AGENTS.md, SOUL.md, USER.md, IDENTITY.md, TOOLS.md, HEARTBEAT.md)
├── cli/
│   └── commands.py     # Typer CLI entry point (onboard, agent, gateway, status, provider, channels, cron)
└── utils/
    └── helpers.py      # Path resolution, filename sanitization, session key helpers
```

---

## Message Flow

```
User sends message via Channel (Telegram/Discord/CLI/etc.)
        ↓
    MessageBus.inbound queue
        ↓
    AgentLoop._process_message()
        ├── SessionManager.get_history() → past messages
        ├── ContextBuilder.build() → system prompt + bootstrap + memory + skills
        ├── _run_agent_loop():
        │     LLM.chat(messages) → response
        │     while response has tool_calls:
        │         ToolRegistry.execute(each tool) → results
        │         append results to messages
        │         LLM.chat(messages) → response
        │     return final content
        ├── SessionManager.save()
        ├── MemoryStore.consolidate() (if enough messages accumulated)
        └── MessageBus.outbound.put(response)
                ↓
        Channel sends response to user
```

---

## Key Classes

| Class | File | Role |
|---|---|---|
| `AgentLoop` | `agent/loop.py` | Orchestrates everything: msg intake → LLM calls → tool execution → response |
| `ContextBuilder` | `agent/context.py` | Assembles system prompt from bootstrap files, memory, skills, runtime context |
| `MemoryStore` | `agent/memory.py` | Reads/writes MEMORY.md (long-term facts) and HISTORY.md (searchable event log) |
| `Tool` (ABC) | `agent/tools/base.py` | Interface: `name`, `description`, `parameters` (JSON Schema), `execute(**kwargs) → str` |
| `ToolRegistry` | `agent/tools/registry.py` | Registers tools, generates schemas for LLM, dispatches execution |
| `SessionManager` | `session/manager.py` | Append-only JSONL per conversation. Tracks `last_consolidated` offset |
| `LLMProvider` (ABC) | `providers/base.py` | Interface: `chat(messages, tools) → response` |
| `LiteLLMProvider` | `providers/litellm_provider.py` | Routes to any provider (OpenAI, Anthropic, etc.) via LiteLLM |
| `BaseChannel` (ABC) | `channels/base.py` | Interface: `start()`, `stop()`, `send_message()` |
| `ChannelManager` | `channels/manager.py` | Starts/stops all configured channels |
| `MessageBus` | `bus/queue.py` | Async inbound/outbound queues decoupling channels from agent |
| `CronService` | `cron/service.py` | Scheduled job execution with persistence |
| `HeartbeatService` | `heartbeat/service.py` | Periodic wake-up, checks HEARTBEAT.md for pending tasks |
| `Config` | `config/schema.py` | Pydantic root config model |

---

## Configuration

Stored at `~/.nanobot/config.json`. Pydantic-validated.

```
Config
├── agents.defaults     → model, max_tokens, temperature, max_iterations
├── channels            → telegram/discord/slack/etc. tokens + settings
├── providers           → api_key, api_base per provider (openrouter, anthropic, openai, etc.)
├── gateway             → host, port, heartbeat interval
└── tools               → web search key, exec deny patterns, restrict_to_workspace, mcp_servers
```

Provider resolution order: config key → model keyword match → API key prefix → API base URL → gateway-first fallback.

---

## Tool System

Every tool extends `Tool` ABC:
```python
class MyTool(Tool):
    name = "my_tool"
    description = "Does something"
    parameters = {"type": "object", "properties": {...}}
    async def execute(self, **kwargs) -> str: ...
```

Register in `ToolRegistry`. LLM sees tools as OpenAI function-calling schema. Tool results are strings (errors included — with hint suffix).

**Built-in tools**: `exec`, `read_file`, `write_file`, `edit_file`, `list_dir`, `web_search`, `web_fetch`, `message`, `spawn`, `cron`.

**MCP tools**: Auto-discovered from configured MCP servers, wrapped as `mcp_{server}_{tool}`.

---

## Workspace & Bootstrap

`~/.nanobot/workspace/` contains files that define the agent's personality and behavior:

| File | Purpose |
|---|---|
| `AGENTS.md` | Agent behavior rules and constraints |
| `SOUL.md` | Personality and values |
| `USER.md` | Info about the user |
| `IDENTITY.md` | Agent name and bio |
| `TOOLS.md` | Tool usage instructions |
| `HEARTBEAT.md` | Periodic task checklist (markdown checkboxes) |
| `memory/MEMORY.md` | Long-term facts (updated by LLM via consolidation) |
| `memory/HISTORY.md` | Chronological event log (grep-searchable) |

---

## Skills

Directory-based. Each skill = folder with `SKILL.md`.

- **Bundled**: `nanobot/skills/` (memory, github, weather, tmux, cron, summarize, clawhub, skill-creator)
- **Custom**: `~/.nanobot/workspace/skills/`
- Can be "always-loaded" (in system prompt) or "available" (loaded on demand)

---

## Session & Memory

**Sessions**: JSONL files in `~/.nanobot/data/sessions/`, keyed by `channel:chat_id`. Append-only for LLM cache efficiency.

**Consolidation**: After enough messages accumulate, old messages are summarized by the LLM into MEMORY.md (facts) and HISTORY.md (events). `last_consolidated` tracks the boundary.

---

## CLI Commands

```
nanobot onboard           # First-time setup wizard
nanobot agent             # Interactive chat (prompt_toolkit)
nanobot agent -m "msg"    # Single message mode
nanobot gateway           # 24/7 server: channels + agent + cron + heartbeat
nanobot status            # Provider and channel status
nanobot provider login X  # OAuth login (copilot, codex)
nanobot channels login    # WhatsApp QR scan
nanobot cron add|list|rm  # Manage scheduled tasks
```

Entry point: `nanobot.cli.commands:app` (Typer).

---

## Running Modes

1. **CLI** — `nanobot agent` — direct terminal interaction
2. **Gateway** — `nanobot gateway` — long-running server with channels, cron, heartbeat
3. **Docker** — mount `~/.nanobot` for persistence

---

## Security

- Shell exec has deny patterns (rm -rf, format, fork bombs, etc.)
- `restrict_to_workspace` sandboxes file tools to workspace dir
- `resolve_path()` prevents path traversal
- `allowFrom` whitelists user/sender IDs per channel

---

## Adding a New Provider

1. Add `ProviderSpec` to `PROVIDERS` tuple in `providers/registry.py`
2. Add config field to `ProvidersConfig` in `config/schema.py`

## Adding a New Tool

1. Create class extending `Tool` in `agent/tools/`
2. Register it in `ToolRegistry` (done in `AgentLoop.__init__`)

## Adding a New Channel

1. Create class extending `BaseChannel` in `channels/`
2. Add config to `ChannelsConfig` in `config/schema.py`
3. Register in `ChannelManager`

---

## Tests

`tests/` — pytest + pytest-asyncio. Covers tool validation, cron, heartbeat, prompt caching, memory consolidation, CLI, email channel.
