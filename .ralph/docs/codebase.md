# nanobot Codebase Overview

This document describes the existing nanobot codebase structure so you can integrate properly.

## Project Structure

```
nanobot/
├── agent/              # Core agent functionality
│   ├── loop.py         # AgentLoop - main processing engine
│   ├── context.py      # ContextBuilder - assembles prompts
│   ├── memory.py       # MemoryStore - current simple memory
│   ├── skills.py       # SkillsLoader - loads skill definitions
│   ├── subagent.py     # SubagentManager - handles spawned agents
│   └── tools/          # Tool implementations
│       ├── base.py     # BaseTool abstract class
│       ├── registry.py # ToolRegistry
│       ├── filesystem.py
│       ├── shell.py
│       ├── web.py
│       ├── message.py
│       ├── spawn.py
│       └── cron.py
├── providers/          # LLM providers
│   ├── base.py         # LLMProvider abstract class
│   ├── litellm_provider.py  # Main provider (use this)
│   ├── transcription.py
│   └── registry.py
├── channels/           # Chat channel integrations
│   ├── telegram/
│   ├── feishu/
│   └── ...
├── config/             # Configuration
│   ├── schema.py       # Config dataclasses
│   └── loader.py
├── bus/                # Message bus
│   ├── events.py       # InboundMessage, OutboundMessage
│   └── queue.py        # MessageBus
├── session/            # Session management
│   └── manager.py      # SessionManager
├── cron/               # Scheduled tasks
│   ├── service.py
│   └── types.py
└── cli/                # Command line interface
```

## Key Classes to Know

### AgentLoop (agent/loop.py)

The main processing engine. Flow:
1. Receives `InboundMessage` from bus
2. Uses `ContextBuilder` to build prompt
3. Calls LLM via `LLMProvider`
4. Executes tool calls via `ToolRegistry`
5. Sends `OutboundMessage` back

```python
class AgentLoop:
    def __init__(self, bus, provider, workspace, ...):
        self.bus = bus
        self.provider = provider
        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
```

### ContextBuilder (agent/context.py)

Assembles the context for LLM calls:
- `build_system_prompt()` — loads bootstrap files, memory, skills
- `build_messages()` — combines system prompt + history + current message

**This is where memory integration happens.** The new memory system will hook into `build_messages()` to inject context packets.

### MemoryStore (agent/memory.py)

Current simple memory implementation. Just loads MEMORY.md file.

**We are REPLACING this** with the new memory architecture, but keeping the interface.

### LLMProvider (providers/base.py)

Abstract base for LLM calls:

```python
class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages, tools=None, model=None) -> CompletionResult:
        pass
```

Use `litellm_provider.py` for all LLM calls (already handles routing).

### SessionManager (session/manager.py)

Manages conversation sessions:
- Stores conversation history
- Handles session lookup by channel/chat_id

## Integration Points

### For Memory Architecture

1. **Conversation Store** — hook into `AgentLoop.process_message()` to capture turns
2. **Triage Agent** — insert before main agent processing in loop
3. **Memory Agent / Curator** — called when triage says memory needed
4. **Context Injection** — modify `ContextBuilder.build_messages()` to accept context packets

### Code Patterns

**Async everywhere:**
```python
async def my_function():
    result = await some_async_call()
    return result
```

**Tool definition:**
```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something"
    
    def get_parameters(self) -> dict:
        return {"type": "object", "properties": {...}}
    
    async def execute(self, **kwargs) -> str:
        # Do work
        return "result"
```

**LLM calls via litellm:**
```python
from litellm import acompletion

response = await acompletion(
    model="claude-3-haiku-20240307",
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=500,
)
text = response.choices[0].message.content
```

## Config Location

Add new config options to `config/schema.py`:

```python
@dataclass
class MemoryConfig:
    enabled: bool = True
    triage_model: str = "claude-3-haiku-20240307"
    triage_sensitivity: int = 5  # 1-10
    embedding_model: str = "all-MiniLM-L6-v2"
    db_path: str = "~/.nanobot/memory.lance"
```

## Testing

Test files go in `tests/`:
- `tests/test_store.py`
- `tests/test_search.py`
- etc.

Use pytest with async support:
```python
import pytest

@pytest.mark.asyncio
async def test_something():
    result = await my_async_function()
    assert result == expected
```

Mock LLM calls:
```python
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_with_mocked_llm():
    with patch("nanobot.memory.curator.acompletion") as mock:
        mock.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="response"))]
        )
        result = await function_under_test()
```
