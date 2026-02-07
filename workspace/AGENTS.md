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
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in your memory files
- Always run `ruff check nanobot/` and fix any issues before committing
- Always run `pytest` to verify tests pass after making changes
