# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Philosophy

**Ultra-Lightweight**: nanobot maintains a core agent codebase of ~4,300 lines (excluding channels/, cli/, providers/). This is by design — the project prioritizes simplicity and readability over feature completeness. When adding features, consider whether they align with this philosophy or if they should be optional/external.

Run `bash core_agent_lines.sh` to verify the current line count. The script counts lines in: agent/, agent/tools/, bus/, config/, cron/, heartbeat/, session/, utils/, plus root files.

Current line count: **4,355 lines** (as of latest commit)

**Provider Agnostic**: The agent supports multiple LLM providers (OpenRouter, Anthropic, OpenAI, Gemini, Groq, DeepSeek, Zhipu, vLLM, Moonshot) through a unified LiteLLM interface. Provider selection is automatic based on model name keywords in `Config._match_provider()`.

**Channel Abstraction**: All communication channels (Telegram, WhatsApp, Discord, Feishu) inherit from `BaseChannel` and communicate via the message bus. This decouples channel-specific code from the agent processing loop.

## Development Commands

**Testing**
```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_tool_validation.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=nanobot

# Run specific test class
pytest tests/test_vision.py::TestVisionFormatSupport

# Run with debugger
pytest --pdb
```

**Linting**
```bash
# Run ruff linter
ruff check nanobot/

# Auto-fix lint issues
ruff check --fix nanobot/
```

**Line Count Verification**
```bash
# Check current core agent line count
bash core_agent_lines.sh
```

**Installation**
```bash
# Install in editable mode (for development)
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"
```

**Running the bot**
```bash
# Initialize config and workspace
nanobot onboard

# Chat with the agent
nanobot agent -m "Your message here"

# Interactive chat mode
nanobot agent

# Start the gateway (connects to Telegram/WhatsApp)
nanobot gateway

# Send an image for analysis (CLI)
nanobot agent -m "What's in this image?" --image photo.jpg

# Enable voice mode (via chat interface)
nanobot agent -m "Turn on voice mode"
```

**Scheduled Tasks (Cron)**
```bash
# Add a scheduled job
nanobot cron add --name "daily" --message "Good morning!" --cron "0 9 * * *"
nanobot cron add --name "hourly" --message "Check status" --every 3600

# List jobs
nanobot cron list

# Remove a job
nanobot cron remove <job_id>
```

**Channel Management**
```bash
# Login to WhatsApp (scan QR code)
nanobot channels login

# Check channel status
nanobot channels status

# Show overall status
nanobot status
```

## Architecture Overview

nanobot is an ultra-lightweight AI assistant framework (~4,300 lines). The architecture is built around a message bus that decouples communication channels from the agent processing loop.

Current core agent: **4,355 lines** (run `bash core_agent_lines.sh` to verify)

### Core Components

**Agent Loop** (`nanobot/agent/loop.py`)
- Central processing engine that implements the LLM tool-calling loop
- Receives messages from the bus, builds context, calls LLM, executes tools
- Supports subagents for background task execution via the `spawn` tool
- Handles both user messages and system messages (from subagents)

**Context Builder** (`nanobot/agent/context.py`)
- Constructs prompts from multiple sources: bootstrap files, memory, skills, history
- Loads workspace files (AGENTS.md, SOUL.md, USER.md, TOOLS.md) into system prompt
- Manages progressive skill loading (always-loaded vs available skills)
- Handles image/media attachments with base64 encoding

**Message Bus** (`nanobot/bus/`)
- `InboundMessage` and `OutboundMessage` events
- `MessageBus` provides async queue-based routing
- Decouples channels (Telegram, WhatsApp, CLI) from agent logic
- Supports system messages for subagent result announcements

**Subagent System** (`nanobot/agent/subagent.py`)
- `SpawnTool` allows the agent to create background workers
- Subagents run isolated with focused system prompts
- Cannot spawn other subagents or send messages (security/composition boundary)
- Results announced back via system messages on the bus

**Channels** (`nanobot/channels/`)
- `TelegramChannel` - Long polling via python-telegram-bot, supports photos, voice messages, video, documents
- `WhatsAppChannel` - Node.js bridge integration
- `DiscordChannel` - Gateway WebSocket with automatic reconnection and rate limit handling
- `FeishuChannel` - WebSocket long connection (no webhook/public IP required)
- Convert markdown to platform-specific formats (e.g., `_markdown_to_telegram_html`)

**Tools** (`nanobot/agent/tools/`)
- `Tool` base class with `name`, `description`, `parameters`, `execute()`
- `ToolRegistry` manages tool registration and execution
- Built-in tools: file operations, shell execution, web search/fetch, message, spawn

**Skills System** (`nanobot/agent/skills.py`)
- Skills are markdown files (`SKILL.md`) with YAML frontmatter
- Two levels: "always-loaded" (included in prompt) and "available" (loaded on-demand)
- Workspace skills override built-in skills
- Frontmatter may include requirements checking
- **Skills location**: `~/.nanobot/skills/` (workspace) and `nanobot/skills/` (built-in)
- **Skill frontmatter format**:
  ```yaml
  ---
  name: github
  description: GitHub integration
  always_loaded: false
  metadata: '{"nanobot":{"emoji":"🐙","requires":{"bins":["git"],"env":["GITHUB_TOKEN"]}}}'
  ---
  # GitHub Skill

  Instructions for the LLM...
  ```

**Frontmatter metadata options:**
- `nanobot.always: true` - Always load this skill
- `nanobot.emoji` - Emoji icon for skill listings
- `nanobot.requires.bins` - Required executables (checked via `shutil.which()`)
- `nanobot.requires.env` - Required environment variables

**How skills are loaded:**
1. Agent checks workspace (`~/.nanobot/skills/`) first
2. Falls back to built-in skills (`nanobot/skills/`)
3. "Always-loaded" skills included in system prompt
4. "Available" skills loaded when agent requests them via `read_file` tool
5. Skills with unmet requirements shown with `<requires>` tags

**Providers** (`nanobot/providers/litellm_provider.py`)
- LiteLLM wrapper for multi-provider support (OpenRouter, Anthropic, OpenAI, Gemini, etc.)
- Auto-detects provider type from API key format (e.g., `sk-or-` for OpenRouter)
- Supports vLLM and other OpenAI-compatible endpoints
- Provider auto-selection via `Config._match_provider()` based on model name keywords

**Services**
- `CronService` - Scheduled jobs with cron expressions or intervals
- `HeartbeatService` - Periodic wake-up to check workspace/HEARTBEAT.md for tasks
- `SessionManager` - Per-channel conversation history persistence

**Utilities** (`nanobot/utils/`)
- `MediaCleanupRegistry` - Automatic cleanup of temporary media files on exit
- `RateLimiter` - Token-bucket rate limiting for API quotas (TTS, transcription)
- `helpers` - Path resolution and workspace management utilities

### Message Flow Architecture

**Inbound Flow** (User → Agent):
```
User Message → Channel → InboundMessage → MessageBus (inbound queue)
→ AgentLoop._process_message() → ContextBuilder.build()
→ LiteLLM Provider → LLM → Tool Execution → Response
→ OutboundMessage → MessageBus (outbound queue) → Channel → User
```

**Subagent Flow**:
```
Agent uses spawn tool → Subagent created (focused system prompt)
→ Subagent executes → Result published as SystemMessage
→ AgentLoop routes back to original channel
```

**Session Key Format**: `{channel}:{chat_id}` (e.g., `telegram:123456789`)

### Key Patterns

**Tool Context Injection**
Tools like `MessageTool` and `SpawnTool` need to know which chat to respond to. Their context is set dynamically per-message via `set_context(channel, chat_id)` in the agent loop.

**Session Keys**
Sessions are identified by `{channel}:{chat_id}` format. This enables conversation history persistence across different channels.

**System Message Routing**
Subagent results are sent as system messages with `chat_id` set to `"original_channel:original_chat_id"`. The agent loop parses this to route responses back to the correct destination.

**Media Handling Pattern**
Channels handle media downloads before creating `InboundMessage`:
1. Download media to `~/.nanobot/media/`
2. Pass file paths in `media=[...]` parameter
3. ContextBuilder reads files and encodes to base64 for vision
4. Agent receives encoded content in user message
5. For video: VideoProcessor extracts frames/audio before passing to agent

**Video Processing Pattern**
The `VideoProcessor` class handles video analysis:
- Extracts up to `max_frames` key frames using ffmpeg
- Extracts audio track for transcription (if configured)
- Validates file paths are within allowed directories (media/workspace)
- Enforces maximum video size (100MB)
- Registers temporary files for cleanup via `MediaCleanupRegistry`
- Returns both frame paths (for vision) and transcript text

**Bridge Directory**
The `bridge/` directory contains WhatsApp Node.js integration code. It's force-included into the wheel package at `nanobot/bridge` during build (see `pyproject.toml`).

**Channel Manager** (`nanobot/channels/manager.py`)
- Initializes enabled channels from config
- Creates and injects TTS provider if `tools.multimodal.tts.enabled` is true
- Routes outbound messages to appropriate channels
- Manages channel lifecycle (start/stop)

**TTS Provider Injection Pattern**
The TTS provider is initialized in `ChannelManager.__init__()` and passed to channel constructors (e.g., `TelegramChannel`). This follows a dependency injection pattern where channels receive optional provider dependencies for handling specialized features like voice output.

**Media Cleanup Pattern**
When processing temporary media (video frames, audio extracts, etc.), use `MediaCleanupRegistry` to track files for automatic cleanup:
```python
from nanobot.utils import get_cleanup_registry

registry = get_cleanup_registry()
registry.register(temp_file_path)  # Cleaned up on process exit
```

**Rate Limiting Pattern**
For expensive operations (TTS, transcription), use rate limiters to prevent abuse:
```python
from nanobot.utils import TTSRateLimiter

limiter = TTSRateLimiter()
allowed, error = limiter.is_allowed(user_id)
if not allowed:
    return error  # Rate limit exceeded
```

## Adding New Channels

To add a new chat platform:

1. **Create channel class** in `nanobot/channels/{platform}.py`:
   - Inherit from `BaseChannel`
   - Implement `start()`, `stop()`, `send()` methods
   - Convert incoming messages to `InboundMessage` events
   - Handle outgoing `OutboundMessage` events
   - Convert markdown to platform-specific format

2. **Add config schema** in `nanobot/config/schema.py`:
   ```python
   class PlatformConfig(BaseModel):
       enabled: bool = False
       token: str = ""
       allow_from: list[str] = Field(default_factory=list)
   ```

3. **Register in ChannelManager** (`nanobot/channels/manager.py:_init_channels`)

4. **Update dependencies** in `pyproject.toml` if needed

## Adding New Tools

1. **Create tool class** in `nanobot/agent/tools/{tool_name}.py`:
   ```python
   from nanobot.agent.tools.base import Tool

   class MyTool(Tool):
       name = "my_tool"
       description = "What this tool does"

       @property
       def parameters(self) -> dict:
           return {"type": "object", "properties": {...}}

       async def execute(self, **kwargs) -> str:
           # Tool implementation
           return "result"
   ```

2. **Register in ToolRegistry** (usually automatic via import)

3. **Add to workspace restriction** if needed (see `FileReadTool`, `ShellTool` for examples)

## Adding New Providers

1. **Add provider config** to `nanobot/config/schema.py:ProvidersConfig`
2. **Add keyword mapping** to `nanobot/config/schema.py:Config._match_provider()`
3. **Add to fallback list** in `Config.get_api_key()`
4. **Test with** `nanobot agent -m "test" --model provider/model-name`

## Workspace Structure

The user workspace (`~/.nanobot/` by default) contains:
- `config.json` - Provider API keys, channel config, model settings
- `skills/` - Custom skills (each with `SKILL.md`)
- `memory/MEMORY.md` - Persistent knowledge store
- `memory/YYYY-MM-DD.md` - Daily notes
- `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md` - Bootstrap files loaded into context
- `HEARTBEAT.md` - Tasks for periodic heartbeat service

## Security

**Workspace Restriction** (`tools.restrict_to_workspace`)
When `true`, all file and shell tools are restricted to the workspace directory. This provides sandboxing for production deployments. See SECURITY.md for comprehensive security guidelines.

**How it works:**
- File tools (`FileReadTool`, `FileWriteTool`, `FileEditTool`, `ListTool`) check if paths are within workspace
- Shell tool (`ShellTool`) sets workspace as working directory and validates commands
- Uses `Path.resolve()` and `Path.is_relative_to()` for path validation
- Symlinks are resolved to their targets before validation

**Channel Access Control** (`channels.*.allow_from`)
Each channel supports an allow-list for user IDs. Empty list = allow all (default for personal use). Configure for production to restrict access.

- Telegram: User IDs (integers) from `@userinfobot`
- Discord: User IDs (snowflake integers)
- WhatsApp: Phone numbers with country code (`+1234567890`)
- Feishu: User `open_id` strings (`ou_xxx`)

**API Key Security**
- Keys stored in `~/.nanobot/config.json` (never commit to git)
- `.gitignore` excludes workspace and config
- Keys can also be set via environment variables (`NANOBOT_PROVIDERS__OPENROUTER__API_KEY`)
- Provider-specific overrides available (e.g., `tools.multimodal.tts.api_key`)

**Security Best Practices**
- Set file permissions: `chmod 600 ~/.nanobot/config.json`
- Never run as root
- Use dedicated API keys with spending limits
- Review SECURITY.md for production deployment guidelines

## Configuration

Config file: `~/.nanobot/config.json`

**Model Name Format**
Models must include the provider prefix:
- ✅ `anthropic/claude-opus-4-5`
- ✅ `openai/gpt-4o`
- ❌ `claude-opus-4-5` (missing prefix)

For OpenRouter, Zhipu, Moonshot, vLLM: the prefix is auto-added if missing.

**Provider Auto-Detection** (`nanobot/config/schema.py:Config._match_provider`)
The config schema automatically selects the appropriate provider based on model name keywords:
- `openrouter` → `providers.openrouter`
- `claude`, `anthropic` → `providers.anthropic`
- `openai`, `gpt` → `providers.openai`
- `gemini` → `providers.gemini`
- `deepseek` → `providers.deepseek`
- `groq` → `providers.groq`
- `zhipu`, `glm`, `zai` → `providers.zhipu`
- `moonshot`, `kimi` → `providers.moonshot`
- `vllm` → `providers.vllm`

Key sections:
- `providers` - API keys for OpenRouter, Anthropic, OpenAI, Groq, etc.
- `agents.defaults.model` - Default LLM model
- `channels` - Telegram token/user_id, WhatsApp settings
- `tools.web.search.apiKey` - Brave Search API key (optional)
- `tools.multimodal` - Multi-modal capabilities (vision, TTS, video)
- `exec` - Shell tool configuration (timeout, workspace restrictions)

**Environment Variable Format**
Config can be set via environment variables using `NANOBOT_` prefix and `__` as delimiter:
```bash
export NANOBOT__PROVIDERS__OPENROUTER__API_KEY="sk-or-xxx"
export NANOBOT__AGENTS__DEFAULTS__MODEL="anthropic/claude-opus-4-5"
export NANOBOT__TOOLS__RESTRICT_TO_WORKSPACE="true"
```

### Multi-Modal Support

The codebase includes multi-modal capabilities that are disabled by default and must be explicitly enabled:

**Vision/Image Support** (`nanobot/agent/context.py`, `nanobot/providers/litellm_provider.py`)
- Images are base64-encoded and passed to vision-capable models
- Provider-specific format handling (Claude, Gemini, OpenAI)
- Configuration: `tools.multimodal.vision_enabled`, `tools.multimodal.max_image_size`
- **Implementation**: `_build_user_content()` in ContextBuilder converts images to data URLs

**Text-to-Speech** (`nanobot/providers/tts.py`, `nanobot/agent/tools/voice.py`)
- OpenAI TTS integration for voice output
- `VoiceTool` for enabling/disabling voice mode
- Configuration: `tools.multimodal.tts.enabled`, `tools.multimodal.tts.provider`, `tools.multimodal.tts.voice`
- **Pattern**: TTS provider is injected into channels, which check session metadata for voice mode flag

**Video Processing** (`nanobot/agent/video.py`)
- Frame extraction using ffmpeg for video analysis
- Audio extraction for transcription
- Configuration: `tools.multimodal.max_video_frames`
- **Note**: Requires ffmpeg to be installed on the system

**Voice Transcription** (Groq Whisper)
- If Groq provider is configured, Telegram voice messages are automatically transcribed
- Configured via `providers.groq.apiKey`
- Transcription handled by channel before passing to agent

**How to add multi-modal support to a new channel:**
1. Handle media downloads in `_handle_message()` or equivalent
2. Pass media paths to `InboundMessage(media=[...])`
3. For TTS: check `msg.metadata.get("voice")` in `send()` method
4. For video: use `VideoProcessor` to extract frames before passing to agent

## Line Count Philosophy

The project maintains an ultra-lightweight codebase. Run `bash core_agent_lines.sh` to verify the current line count. The core agent (excluding channels/, cli/, providers/) is currently **4,355 lines**.

**When making changes:**
- Prefer adding optional features over core complexity
- Use external providers/services rather than bundling libraries
- Follow existing patterns rather than creating new abstractions
- Test the line count after significant changes

## Debugging

**Enable verbose logging:**
```bash
# Set log level via environment
export NANOBOT_LOG_LEVEL=DEBUG
nanobot agent -m "test"

# Logs are stored in
~/.nanobot/logs/
```

**Understanding Tool Execution Errors**
Tools return string results that may include error messages. When a tool fails:
1. The error is returned as a string from `execute()`
2. The agent sees the error and can communicate it to the user
3. Check logs for full stack traces
4. Common issues: path not in workspace, command timeout, missing dependencies

**Tracing Message Flow**
```bash
# Enable DEBUG logs to see:
# - Messages received from channels
# - Context building process
# - LLM API calls
# - Tool execution results
# - Response routing

export NANOBOT_LOG_LEVEL=DEBUG
```

**Common issues:**
- **LiteLLM model format**: Ensure model names include provider prefix (e.g., `anthropic/claude-opus-4-5`, not just `claude-opus-4-5`)
- **Channel permissions**: Verify `allow_from` lists are correctly configured with proper user IDs
- **Vision not working**: Check that the model supports vision and `tools.multimodal.vision_enabled` is true
- **TTS not working**: Verify OpenAI API key is configured and `tools.multimodal.tts.enabled` is true
- **Workspace restrictions**: When `tools.restrict_to_workspace` is true, all file/shell operations are sandboxed

**Testing individual components:**
```bash
# Test vision with a specific model
nanobot agent -m "Describe this image" --image test.jpg --model anthropic/claude-opus-4-5

# Check channel status
nanobot channels status

# View current config
cat ~/.nanobot/config.json

# Test TTS
nanobot agent -m "Turn on voice mode"
nanobot agent -m "Tell me a joke"
```

## Testing Guidelines

**Test Structure**
Tests are organized by functionality:
- `test_tool_validation.py` - Tool parameter validation and execution
- `test_vision.py` - Multi-modal vision support and provider format conversion
- Tests use `pytest` with `asyncio_mode = "auto"` for async support

**Testing Patterns**
```python
# Mock external dependencies
from unittest.mock import AsyncMock, MagicMock, patch

# Test class structure
class TestVisionFormatSupport:
    def setup_method(self):
        """Set up test fixtures."""
        self.provider = LiteLLMProvider(...)

    def test_specific_behavior(self):
        """Test individual behaviors in isolation."""
        result = self.provider._has_image_content(...)
        assert result == expected
```

**Running Tests**
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_vision.py

# Run with coverage
pytest --cov=nanobot

# Run with verbose output
pytest -v

# Run specific test class
pytest tests/test_vision.py::TestVisionFormatSupport
```

**When adding new features:**
1. Write tests before or alongside implementation
2. Test both success and failure cases
3. Mock external API calls (LLM providers, HTTP requests)
4. Test edge cases (empty inputs, invalid paths, rate limits)
5. Ensure tests are fast and isolated

## Common Pitfalls

**Model name format:**
- ❌ Wrong: `model: "claude-opus-4-5"`
- ✅ Right: `model: "anthropic/claude-opus-4-5"` (provider prefix required)

**Workspace path issues:**
- Workspace is created on first run if it doesn't exist
- Use `~` for home directory (will be expanded)
- File tools use `Path.resolve()` to handle symlinks correctly

**Channel not receiving messages:**
- Check `allow_from` lists (empty = allow all, non-empty = restrictive)
- Verify bot/token is correct and has permissions
- For Telegram: ensure you've started a conversation with the bot
- For Discord: bot must be invited to server with proper intents

**Vision not working:**
- Ensure model supports vision (Claude 3.5+, GPT-4V, Gemini Pro)
- Check `tools.multimodal.vision_enabled: true`
- Verify image size under `max_image_size` limit
- Check logs for encoding errors

**TTS not working:**
- Verify `tools.multimodal.tts.enabled: true`
- Check OpenAI API key is configured (or TTS-specific key)
- Ensure voice mode is enabled: send `voice('on')` message
- Check channel supports voice output (Telegram does)

**Session state issues:**
- Sessions stored in `~/.nanobot/sessions/` as JSON
- Key format: `{channel}:{chat_id}`
- Clear sessions: `rm ~/.nanobot/sessions/*.json`
- Session includes message history and metadata (voice mode, etc.)

**Rate limiting:**
- Discord: automatic retry with exponential backoff
- OpenAI/Anthropic: handle in application code
- Telegram: respects rate limits automatically via python-telegram-bot

**ffmpeg not found:**
- Video processing requires ffmpeg on system
- Install: `apt install ffmpeg` (Linux) or `brew install ffmpeg` (macOS)
- Check: `ffmpeg -version`
- VideoProcessor logs error if ffmpeg unavailable
