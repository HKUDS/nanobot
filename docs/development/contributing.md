# Contributing guide

Thank you for wanting to contribute to nanobot.

Nanobot lives by one simple belief: useful tools should be calm, clear, and kind to humans. We value solving real problems with minimal code—solutions should be powerful but lightweight, ambitious but not needless.

## Maintainers

| Maintainer | Area |
|--------|---------|
| [@re-bin](https://github.com/re-bin) | Project lead, `main` branch |
| [@chengyongru](https://github.com/chengyongru) | `nightly` branch, experimental features |

## Branch strategy

Nanobot uses a dual-branch model to balance stability and exploration:

| Branch | Purpose | Stability |
|------|------|--------|
| `main` | Stable releases | Production-ready |
| `nightly` | Experimental work | May contain bugs/breaking changes |

### Which branch should I target?

**Target `nightly` if:**

- You're adding new functionality
- You're refactoring behavior or APIs
- You're modifying configuration formats
- You are unsure where to land the change

**Target `main` if:**

- You're fixing bugs without behavior changes
- You're improving documentation
- You're tweaking things that do not affect features

> **Tip:** If in doubt, use `nightly`. Cherry-picking stable features into `main` is safer than rolling back committed changes.

### How does nightly merge into main?

We cherry-pick stable features rather than merging the entire branch:

```
nightly  ──┬── Feature A (stable) ──► PR ──► main
           ├── Feature B (testing)
           └── Feature C (stable) ──► PR ──► main
```

This typically happens weekly, but only when features are verified to be stable.

### Branch selection cheat sheet

| Change type | Target branch |
|------------|---------|
| New feature | `nightly` |
| Bug fix | `main` |
| Docs | `main` |
| Refactor | `nightly` |
| Unsure | `nightly` |

## Development setup

### Clone the repository

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
```

### Install dependencies

Nanobot uses [`uv`](https://github.com/astral-sh/uv) as the package manager:

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (including dev)
uv sync
```

### Verify the installation

```bash
uv run pytest tests/
uv run nanobot status
```

## Code style

We care about passing lint checks, sure, but more importantly we want nanobot to stay small, calm, and readable.

Aim for code that feels:

- **Simple:** fix real problems with the smallest effective change
- **Clear:** optimize for the next reader, not cleverness
- **Decoupled:** keep boundaries tidy and avoid unnecessary abstractions
- **Honest:** don’t hide complexity or invent extra complexity for its own sake
- **Durable:** pick solutions that are easy to maintain, test, and extend

### Specific style rules

- **Line length:** 100 characters (enforced via `ruff`, E501 ignored)
- **Python version:** 3.11+
- **Lint tool:** `ruff` with rulesets E, F, I, N, W
- **Async everywhere:** use `asyncio`, tests rely on `asyncio_mode = "auto"`
- Prefer readable code over magic
- Prefer focused small patches over sweeping rewrites
- New abstractions must reduce complexity, not move it around

### Run lint and format

```bash
uv run ruff check nanobot/
uv run ruff check nanobot/ --fix
uv run ruff format nanobot/
```

## Running tests

### Run all tests

```bash
uv run pytest tests/
```

### Run a single test file

```bash
uv run pytest tests/test_channels.py -v
```

### Run a specific test function

```bash
uv run pytest tests/test_commands.py::test_function_name -v
```

### Testing framework notes

- Test runner: `pytest`
- Async mode: `pytest-asyncio` with `asyncio_mode = "auto"`
- Test files live in `tests/`
- Integration cases live in `case/`

## Writing tests

### Basic structure

```python
# tests/test_my_feature.py
import pytest
from nanobot.agent.loop import AgentLoop


async def test_agent_handles_simple_message():
    """Agent should handle a plain text message."""
    # Setup
    # ...

    # Exercise
    result = await some_function()

    # Verify
    assert result == expected
```

### Async tests

`asyncio_mode = "auto"` means you can write async tests without `@pytest.mark.asyncio`:

```python
async def test_channel_receives_message():
    channel = MockChannel()
    await channel.start()
    # ...
```

### Mocking external dependencies

```python
from unittest.mock import AsyncMock, patch

async def test_llm_call():
    with patch("nanobot.providers.litellm_provider.LiteLLMProvider.chat") as mock_chat:
        mock_chat.return_value = AsyncMock(return_value="mock response")
        # Exercise
        ...
```

## Opening a pull request

### PR checklist

- [ ] All tests pass: `uv run pytest tests/`
- [ ] Lint is clean: `uv run ruff check nanobot/`
- [ ] Code is formatted: `uv run ruff format nanobot/`
- [ ] Target branch is correct (`main` or `nightly`)
- [ ] PR description clearly explains the change and its impact

### PR description suggestions

A good description should include:

1. **Summary:** A sentence or two of what changed
2. **Why:** The motivation or problem addressed
3. **How to test:** Verification steps that demonstrate the change works

### Cherry-picking into main

If a feature is stable on `nightly`, maintainers may cherry-pick it into `main`:

```bash
git checkout main
git cherry-pick <commit-hash>
# Open a new PR into main
```

## Contact and community

If you have questions, ideas, or half-formed insights, feel free to:

- Open a [GitHub Issue](https://github.com/HKUDS/nanobot/issues)
- Join the [Discord community](https://discord.gg/MnCvHqpUGB)
- Join the Feishu/WeChat groups listed in [COMMUNICATION.md](https://github.com/HKUDS/nanobot/blob/main/COMMUNICATION.md)
- Email Xubin Ren (@Re-bin) at xubinrencs@gmail.com

Thank you for investing time and energy into nanobot. We welcome contributions of every size.
