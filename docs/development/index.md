# Development Docs

Welcome to the nanobot development documentation. This section covers architecture, contributing, and building custom plugins.

## Documentation index

| Doc | Description |
|-----|-------------|
| [Architecture overview](./architecture.md) | System design, module relationships, and data flow |
| [Contributing guide](./contributing.md) | Branch strategy, coding style, and PR workflow |
| [Channel plugin development](./channel-plugin.md) | Build custom chat platform integrations |

## Quick start

### Environment setup

```bash
# Clone the repo
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# Install dependencies (including dev extras)
uv sync

# Run the test suite
uv run pytest tests/

# Start a local agent for manual testing
uv run nanobot agent
```

### Core principles

nanobot follows a “less code, more impact” philosophy:

- **Lightweight**: ~16k Python lines deliver the full agent stack
- **Async-first**: `async/await` everywhere to avoid blocking calls
- **Event-driven**: Messages flow through a bus so modules stay loosely coupled
- **Extensible**: Plugin hooks enable custom channels and skills

## Project structure

```
nanobot/
├── agent/          # Core agent logic
│   ├── loop.py     # Agent loop (LLM ↔ tool execution)
│   ├── context.py  # Prompt builder
│   ├── memory.py   # Memory integrations
│   └── tools/      # Built-in tools
├── bus/            # Message bus
├── channels/       # Chat platform interfaces (plugin-friendly)
├── providers/      # LLM provider integrations
├── session/        # Session management
├── config/         # Pydantic schemas
├── skills/         # Bundled skills
├── cron/           # Scheduled task runner
└── heartbeat/      # Periodic wake-up service
```

## Resources

- [GitHub repository](https://github.com/HKUDS/nanobot)
- [Issue tracker](https://github.com/HKUDS/nanobot/issues)
- [Discord community](https://discord.gg/MnCvHqpUGB)
- [Channel Plugin Guide (English)](../CHANNEL_PLUGIN_GUIDE.md)
