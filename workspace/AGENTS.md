# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Commands

### Build/Install
```bash
# Install from source (for development)
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"
```

### Linting
```bash
# Check code style and errors
ruff check nanobot/

# Auto-fix issues
ruff check --fix nanobot/
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_tool_validation.py

# Run specific test function
pytest tests/test_tool_validation.py::test_validate_params_missing_required

# Run with verbose output
pytest -v

# Run specific test with async support
pytest tests/test_tool_validation.py::test_registry_returns_validation_error
```

## Code Style Guidelines

### Python Version
- Python 3.11+ required
- Use modern type hints (PEP 695): `list[str]`, `dict[str, Any]`, `str | None`

### Import Order
1. Standard library imports
2. Third-party imports
3. Local (`nanobot`) imports

Example:
```python
import asyncio
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel

from nanobot.bus.events import InboundMessage
from nanobot.providers.base import LLMProvider
```

### Naming Conventions
- **Classes**: PascalCase (`AgentLoop`, `ToolRegistry`)
- **Functions/Methods**: snake_case (`get_or_create`, `process_message`)
- **Private methods**: Prefix with underscore (`_load`, `_validate`)
- **Constants**: UPPER_SNAKE_CASE (`_TYPE_MAP`, `MAX_ITERATIONS`)
- **Variables**: snake_case

### Type Hints
- Always include return types in function signatures
- Use `str | None` for optional types (not `Optional[str]`)
- Use `dict[str, Any]` for generic dicts
- Use forward references with strings when needed for circular imports

Example:
```python
async def process_message(self, msg: InboundMessage) -> OutboundMessage | None:
    """Process a single inbound message."""
    session = self.sessions.get_or_create(msg.session_key)
    return await self._build_response(session, msg)
```

### Docstrings
- Use triple quotes for module, class, and method docstrings
- Format: Brief description, then Args/Returns sections if needed

Example:
```python
def get_or_create(self, key: str) -> Session:
    """
    Get an existing session or create a new one.
    
    Args:
        key: Session key (usually channel:chat_id).
    
    Returns:
        The session.
    """
```

### Error Handling & Async
- Use try/except with specific exceptions
- In tools, return error messages as strings (not raise exceptions)
- Use loguru logger for error logging: `logger.error(f"Error: {e}")`
- All I/O operations should be async with `async def` and `await`

### File Operations
- Use `pathlib.Path` instead of string paths
- Use `Path.expanduser()`, `Path.read_text(encoding="utf-8")`, `Path.write_text(encoding="utf-8")`
- Use `Path.mkdir(parents=True, exist_ok=True)` to create directories

### Configuration
- Use Pydantic BaseModel for config schemas
- Use `Field(default_factory=...)` for mutable defaults (lists, dicts)

### Line Length
- Maximum line length: 100 characters (configured in ruff)
- Prefer breaking long lines at logical points

### Logging
- Use `loguru` logger for logging
- Import: `from loguru import logger`
- Log levels: `logger.debug()`, `logger.info()`, `logger.warning()`, `logger.error()`

### Testing
- Use pytest for testing
- Test function names: `test_<what_is_being_tested>`

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in your memory files
- Always run `ruff check nanobot/` and fix any issues before committing
- Always run `pytest` to verify tests pass after making changes

## Auto-Memory System

nanobot includes an intelligent auto-memory system that automatically:

1. **Tracks conversations** — Counts user messages and triggers summaries at intervals
2. **Extracts key information** — Topics, preferences, decisions, tasks, technical issues
3. **Generates daily summaries** — Creates `memory/YYYY-MM-DD.md` files
4. **Updates long-term memory** — Saves important insights to `memory/MEMORY.md`

### When to Use Memory

The auto-memory system runs automatically, but you should also proactively save information when:

- User asks you to "remember" something
- User states a preference ("I like...")
- User makes a decision ("I'll use...")
- You solve a technical problem
- User mentions important context for future use

### Memory Files

- `~/.nanobot/workspace/memory/YYYY-MM-DD.md` — Daily conversation summary
- `~/.nanobot/workspace/memory/MEMORY.md` — Long-term insights

### Reading Memory

When helping a user, first read their memory:

```python
# Read long-term memory
memory_content = Path.home() / ".nanobot" / "workspace" / "memory" / "MEMORY.md"
if memory_content.exists():
    existing_memory = memory_content.read_text(encoding="utf-8")
    # Use this context in your responses
```

### Writing to Memory

The auto-memory system handles most cases, but you can manually update memory:

```python
# Update long-term memory
memory_file = Path.home() / ".nanobot" / "workspace" / "memory" / "MEMORY.md"
new_info = "**用户偏好** 简洁的代码风格"
memory_file.write_text(memory_file.read_text() + "\n\n" + new_info, encoding="utf-8")
```

### Best Practices

1. **Use auto-memory** — Let the system track conversations automatically
2. **Be concise** — Summaries should be brief but informative
3. **Prioritize** — Only record information that's likely to be useful later
4. **Deduplicate** — Check existing memory before adding new information
5. **Format consistently** — Use markdown headers and bullet points
