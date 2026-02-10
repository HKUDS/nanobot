# Repository Guidelines

## MCP Tools

Always use Context7 MCP when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.

## Nanobot Core Principles

- Ultra-lightweight core (~4,000 lines) over framework bloat.
- Research-ready, readable code over hidden complexity.
- Fast startup and low resource usage to maximize iteration speed.
- Easy onboarding and deployment with minimal setup friction.
- Quintessence: radical simplicity to maximize learning speed, development velocity, and practical impact.

Context7 Library IDs for this project (use to skip library-matching):

| Library    | Context7 ID             |
| ---------- | ----------------------- |
| LiteLLM    | `/berriai/litellm`      |
| Pydantic   | `/pydantic/pydantic`    |
| Typer      | `/fastapi/typer`        |
| Pytest     | `/pytest-dev/pytest`    |
| Ruff       | `/astral-sh/ruff`       |
| TypeScript | `/microsoft/typescript` |

## Project Structure & Module Organization

- `nanobot/` contains the Python application code (agent loop, tools, channels, providers, CLI, config, cron, session).
- `tests/` contains `pytest` suites plus `test_docker.sh` for container smoke testing.
- `bridge/` contains the TypeScript WhatsApp bridge (`src/` source, `dist/` build output).
- `workspace/` is runtime workspace content (agent notes/memory) and is not core library code.
- Root files include packaging/config (`pyproject.toml`), container setup (`Dockerfile`), and project docs (`README.md`, `SECURITY.md`).

## Build, Test, and Development Commands

- `pip install -e ".[dev]"`: install Nanobot in editable mode with test/lint dependencies.
- `nanobot onboard`: initialize local config and workspace.
- `nanobot agent` or `nanobot agent -m "Hello"`: run interactive or one-shot chat.
- `nanobot gateway`: run channel gateway integrations.
- `pytest`: run Python tests.
- `ruff check .`: run lint checks.
- `bash tests/test_docker.sh`: build image and run Docker smoke checks.
- `cd bridge && npm install && npm run build`: build the TypeScript bridge (`npm run dev` for local run).

## Coding Style & Naming Conventions

- Target Python 3.11+ and keep new code type-annotated.
- Use 4-space indentation; `snake_case` for modules/functions/variables; `PascalCase` for classes.
- Follow Ruff settings in `pyproject.toml` (line length 100, rules `E,F,I,N,W`).
- Keep features in the matching package (for example, channel logic in `nanobot/channels/`, provider logic in `nanobot/providers/`).

## Testing Guidelines

- Use `pytest` with `pytest-asyncio` for async paths.
- Test files and test functions should follow `test_*.py` and `test_*` naming.
- Add/update tests in `tests/` for behavior changes, especially tool validation, channel handling, and provider routing.
- Prefer deterministic unit tests (mocks/monkeypatch) over live network dependencies.

## Commit & Pull Request Guidelines

- Follow the Conventional Commits specification for all commit messages.
- Mirror existing commit style: `feat:`, `fix:`, `docs:`, `refactor:`, and scoped forms like `feat(email): ...`.
- Keep commit titles imperative and concise.
- PRs should include: summary, rationale, test evidence (`pytest`, `ruff`, relevant bridge/docker commands), and linked issues.
- Update docs/config examples when changing CLI behavior, provider setup, or channel integration flows.

## Security & Configuration Tips

- Do not commit API keys or local secrets; keep them in `~/.nanobot/config.json`.
- For safer production operation, enable `tools.restrictToWorkspace` in config.
