# Contributing to nanobot

Thank you for your interest in contributing! This guide will help you get started.

## Maintainers

| Maintainer | Focus |
|------------|-------|
| [@re-bin](https://github.com/re-bin) | Project lead, `main` branch |
| [@chengyongru](https://github.com/chengyongru) | `nightly` branch, experimental features |

## Branching Strategy

nanobot uses a two-branch model to balance stability and innovation:

| Branch | Purpose | Stability |
|--------|---------|-----------|
| `main` | Stable releases | Production-ready |
| `nightly` | Experimental features | May have bugs or breaking changes |

### Which Branch Should I Target?

**Target `nightly` if your PR includes:**

- New features or functionality
- Refactoring that may affect existing behavior
- Changes to APIs or configuration

**Target `main` if your PR includes:**

- Bug fixes with no behavior changes
- Documentation improvements
- Minor tweaks that don't affect functionality

**When in doubt, target `nightly`.** It's easier to cherry-pick stable changes to `main` than to revert unstable changes.

### How Does Nightly Get Merged to Main?

We don't merge the entire `nightly` branch. Instead, stable features are **cherry-picked** from `nightly` into individual PRs targeting `main`:

```
nightly  ──┬── feature A (stable) ──► PR ──► main
           ├── feature B (testing)
           └── feature C (stable) ──► PR ──► main
```

This happens approximately **once a week**, but the timing depends on when features become stable enough.

### Quick Summary

| Your Change | Target Branch |
|-------------|---------------|
| New feature | `nightly` |
| Bug fix | `main` |
| Documentation | `main` |
| Refactoring | `nightly` |
| Unsure | `nightly` |

## Development Setup

```bash
# Clone the repository
git clone https://github.com/HKUDS/nanobot.git
cd nanobot

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint code
ruff check nanobot/

# Format code
ruff format nanobot/
```

## Code Style

- Line length: 100 characters (ruff)
- Target: Python 3.11+
- Linting: `ruff` with rules E, F, I, N, W (E501 ignored)
- Async: Uses `asyncio` throughout; pytest with `asyncio_mode = "auto"`

## Questions?

Feel free to open an [issue](https://github.com/HKUDS/nanobot/issues) or join our community:

- [Discord](https://discord.gg/MnCvHqpUGB)
- [Feishu/WeChat](./COMMUNICATION.md)
