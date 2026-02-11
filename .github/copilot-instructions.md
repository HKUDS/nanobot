# GitHub Copilot Instructions for nanobot

## Project Overview

nanobot is an ultra-lightweight personal AI assistant framework written in Python. The project emphasizes:
- **Minimalism**: Core agent functionality in ~4,000 lines of code
- **Clean code**: Easy to understand, modify, and extend for research
- **Fast**: Minimal footprint for quick iterations

## Code Standards

### Linting and Formatting

- **Ruff** is used for linting and formatting
- Pre-commit hooks automatically run ruff on all commits
- Configuration: `pyproject.toml` (select E,F,I,N,W; ignore E501)
- Run `pre-commit install` to set up hooks locally
- CI runs all pre-commit hooks to ensure consistency

### Python Style

- Follow PEP 8 naming conventions (snake_case for variables/functions)
- **Exception**: Some API parameter names use camelCase for backward compatibility (marked with `# noqa: N803`)
- Line length limit: 100 characters (E501 is ignored)
- Use type hints where appropriate
- Use `from typing import TYPE_CHECKING` for forward references to avoid circular imports

### Import Organization

- Imports are sorted automatically by ruff
- Standard library imports first
- Third-party imports second
- Local imports last
- Use absolute imports from the `nanobot` package

## Architecture

Key components:
- **Agent Loop** (`nanobot/agent/loop.py`): Core processing engine
- **Context Builder** (`nanobot/agent/context.py`): Assembles prompts for LLM
- **Tools** (`nanobot/agent/tools/`): Agent capabilities (filesystem, shell, web, etc.)
- **Channels** (`nanobot/channels/`): Chat platform integrations (Telegram, Discord, etc.)
- **Providers** (`nanobot/providers/`): LLM provider integrations (OpenAI, Anthropic, etc.)
- **Message Bus** (`nanobot/bus/`): Decouples channels from agent core

## Development Workflow

### Making Changes

1. Run linters before committing: `ruff check .`
2. Format code: `ruff format .`
3. Pre-commit hooks will run automatically
4. Tests are in the `tests/` directory - run with `pytest`

### Adding New Features

- **New Tool**: Extend `nanobot.agent.tools.base.Tool` and register in `ToolRegistry`
- **New Channel**: Extend `nanobot.channels.base.Channel` and add to `ChannelManager`
- **New Provider**: Extend `nanobot.providers.base.LLMProvider` and register in provider registry

### Git Workflow

- The reformatting commit `a6c7a1f484e691bc96d7d8a8836fc5f1b9979de3` is in `.git-blame-ignore-revs`
- Configure locally: `git config blame.ignoreRevsFile .git-blame-ignore-revs`

## Testing

- Use `pytest` for testing
- Async tests use `pytest-asyncio`
- Configuration in `pyproject.toml`: `asyncio_mode = "auto"`
- Keep tests focused and maintainable

## Important Conventions

### Naming

- Use descriptive names that reflect the purpose
- Tool classes end with `Tool` (e.g., `ReadFileTool`)
- Channel classes end with `Channel` (e.g., `TelegramChannel`)
- Provider classes end with `Provider` (e.g., `LiteLLMProvider`)

### Error Handling

- Tools should return error messages as strings rather than raising exceptions
- Use try/except blocks to catch and format errors appropriately
- Log errors with `loguru.logger` for debugging

### Documentation

- Update README.md for user-facing changes
- Update SECURITY.md for security-related changes
- Keep docstrings concise and accurate
- Use markdown files in workspace/ for agent instructions (separate from dev docs)

## Dependencies

- Add dependencies to `pyproject.toml` under `dependencies` or `dev` optional dependencies
- Keep dependencies minimal to maintain the lightweight philosophy
- Use `pip install -e .[dev]` for development installation

## Security

- Never commit secrets or API keys
- Use environment variables for sensitive configuration
- Check the GitHub advisory database before adding dependencies
- Follow guidance in `SECURITY.md`

## No Breaking Changes

- When refactoring, maintain backward compatibility for public APIs
- Tool parameter names in schemas must match function signatures
- Document any necessary breaking changes clearly in PR descriptions
