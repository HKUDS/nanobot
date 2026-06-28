# Repository Guidelines

## Project Structure & Module Organization

`nanobot/` contains the Python package. Core agent behavior is in `nanobot/agent/`, channel integrations in `nanobot/channels/`, CLI entry points in `nanobot/cli/`, config models in `nanobot/config/`, providers in `nanobot/providers/`, and skills in `nanobot/skills/`. The WhatsApp bridge is a separate TypeScript project in `bridge/`, with sources in `bridge/src/`. Runtime documents and memory live under `workspace/`; keep root contributor guidance separate from those files.

## Build, Test, and Development Commands

- `pip install -e ".[dev]"`: install nanobot locally with pytest and ruff.
- `nanobot onboard`: create local config.
- `nanobot agent -m "What is 2+2?"`: run a CLI smoke test.
- `nanobot gateway`: run configured chat channels.
- `pytest`: run Python tests from `tests/` when present.
- `ruff check nanobot`: lint Python code.
- `cd bridge && npm install`: install bridge dependencies.
- `cd bridge && npm run build`: compile TypeScript to `bridge/dist/`.
- `cd bridge && npm run dev`: build and run the WhatsApp bridge locally.

## Coding Style & Naming Conventions

Python targets 3.11+ and uses ruff with a 100-character line length. Follow standard Python naming: `snake_case` for functions and modules, `PascalCase` for classes, and typed Pydantic models for configuration schemas. TypeScript uses strict ES2022 modules; keep bridge source files under `bridge/src/` and prefer explicit types at integration boundaries.

## Testing Guidelines

`pyproject.toml` configures pytest with `tests/` as the test root and `pytest-asyncio` in auto mode. No root test suite is currently checked in, so add focused tests with new behavior. Use `test_*.py` names and mirror the package area being exercised, for example `tests/agent/test_context.py`. For bridge changes, add TypeScript tests only after adding a test runner to `bridge/package.json`.

## Commit & Pull Request Guidelines

Recent history uses short, imperative messages such as `update readme`; keep commits concise and scoped. Pull requests should describe the behavior change, list validation commands, link related issues, and include screenshots or terminal output for CLI changes. Note configuration or credential requirements without committing secrets.

## Security & Configuration Tips

Local secrets belong in `~/.nanobot/config.json`, not in the repository. Treat API keys, chat tokens, and WhatsApp session data as private. Avoid committing generated `bridge/dist/`, virtual environments, caches, or workspace memory unless intended.
