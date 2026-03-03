# Contributing to nanobot

Thank you for your interest in contributing to nanobot! This document explains how to set up a development environment and submit changes.

## Development setup

1. **Clone and install from source** (recommended for development):

   ```bash
   git clone https://github.com/HKUDS/nanobot.git
   cd nanobot
   pip install -e ".[dev]"
   ```

   The `[dev]` extra installs pytest, pytest-asyncio, and ruff for testing and linting.

2. **Verify the install**:

   ```bash
   nanobot status
   ```

## Code style and linting

- The project uses [Ruff](https://docs.astral.sh/ruff/) for linting. Configuration is in `pyproject.toml` (`[tool.ruff]`).
- Run the linter before submitting:

  ```bash
  ruff check nanobot tests
  ruff format nanobot tests
  ```

## Running tests

- Tests live in the `tests/` directory and use pytest.
- Run the full test suite:

  ```bash
  pytest tests/ -v
  ```

- Asyncio tests are enabled via `pytest-asyncio` with `asyncio_mode = "auto"` in `pyproject.toml`.

## Submitting changes

1. **Fork** the [nanobot repository](https://github.com/HKUDS/nanobot) on GitHub (if you haven’t already).
2. **Create a branch** from `main` for your change:

   ```bash
   git checkout main
   git pull origin main
   git checkout -b your-branch-name
   ```

3. **Make your changes**, add or update tests if applicable, and ensure:

   - `ruff check nanobot tests` and `ruff format nanobot tests` pass.
   - `pytest tests/ -v` passes.

4. **Commit** with a clear message (e.g. `fix(module): description` or `docs: update README`).
5. **Push** your branch to your fork and open a **Pull Request** against `HKUDS/nanobot` `main`.
6. In the PR description, briefly explain the change and reference any related issues (e.g. `Fixes #123`).

## Project structure

- `nanobot/agent/` — Core agent logic (loop, context, memory, tools).
- `nanobot/channels/` — Chat channel integrations (Telegram, Discord, etc.).
- `nanobot/providers/` — LLM providers (OpenRouter, Anthropic, etc.).
- `nanobot/config/` — Configuration schema and loading.
- `nanobot/skills/` — Bundled skills.
- `tests/` — Test suite.

For more detail, see the [Project Structure](https://github.com/HKUDS/nanobot#-project-structure) section in the README.

## Roadmap and ideas

The [README](https://github.com/HKUDS/nanobot#-contribute--roadmap) lists roadmap items (e.g. multi-modal, long-term memory, more integrations). You can also browse [open issues](https://github.com/HKUDS/nanobot/issues) and [discussions](https://github.com/HKUDS/nanobot/discussions) for ideas.

If you have questions, open a [Discussion](https://github.com/HKUDS/nanobot/discussions) or reach out via the channels in [COMMUNICATION.md](COMMUNICATION.md).

Thanks again for contributing!
