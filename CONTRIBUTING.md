# Contributing to nanobot

## Development Setup

```bash
# Clone the repository
git clone <repository-url>
cd nanobot

# Install dependencies
uv sync

# Install pre-commit hooks (recommended)
uv run pre-commit install
```

## Pre-commit Hooks

This project uses pre-commit hooks to automatically format code with ruff before each commit.

### Installation

```bash
uv run pre-commit install
```

### What it does

When you run `git commit`, the hook will:
1. Automatically run `ruff format` on your code
2. If files are reformatted, add them to staging automatically
3. Complete the commit with formatted code

### Manual usage

```bash
# Run all hooks manually
uv run pre-commit run --all-files

# Skip hooks for one commit
git commit --no-verify -m "message"
```

### Uninstall

```bash
uv run pre-commit uninstall
```

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Format code
uv run ruff format

# Check linting
uv run ruff check

# Fix linting issues
uv run ruff check --fix
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test
uv run pytest tests/test_file.py
```