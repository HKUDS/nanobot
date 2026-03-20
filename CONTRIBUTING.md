# Contributing to GeoClaw

Thank you for being here.

This repository now contains two layers:

- `geoclaw/`: the primary product layer, focused on reproducible geospatial workflows
- `nanobot/`: the inherited lightweight agent runtime that GeoClaw extends

When contributing, please keep the separation clear: geospatial workflow behavior, tools, schemas, renderers, and skills should live under `geoclaw/`, while generic runtime improvements should remain in `nanobot/`.

GeoClaw is built with a simple belief: geospatial tooling should feel calm, clear, reproducible, and safe to run locally.
We care deeply about useful features, but we also believe in achieving more with less:
solutions should be powerful without becoming heavy, and ambitious without becoming
needlessly complicated.

This guide is not only about how to open a PR. It is also about how we hope to build
software together: with care, clarity, and respect for the next person reading the code.

## Maintainers

| Maintainer | Focus |
|------------|-------|
| [@re-bin](https://github.com/re-bin) | Project lead, `main` branch |
| [@chengyongru](https://github.com/chengyongru) | `nightly` branch, experimental features |

## Branching Strategy

We use a two-branch model to balance stability and exploration:

| Branch | Purpose | Stability |
|--------|---------|-----------|
| `main` | Stable releases | Production-ready |
| `nightly` | Experimental features | May have bugs or breaking changes |

### Which Branch Should I Target?

**Target `nightly` if your PR includes:**

- New features or functionality
- Refactoring that may affect existing behavior
- Changes to APIs or configuration
- New GeoClaw workflow capabilities or geospatial tools

**Target `main` if your PR includes:**

- Bug fixes with no behavior changes
- Documentation improvements
- Minor tweaks that don't affect functionality

**When in doubt, target `nightly`.** It is easier to move a stable idea from `nightly`
to `main` than to undo a risky change after it lands in the stable branch.

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

Keep setup boring and reliable. The goal is to get you into the code quickly:

```bash
# Clone the repository
cd geoclaw

# Install with dev dependencies
pip install -e ".[dev]"

# Install GeoClaw's geospatial stack too (recommended for this fork)
pip install -e ".[geo]"

# Run tests
pytest

# Lint code
ruff check nanobot/ geoclaw/ tests/

# Format code
ruff format nanobot/ geoclaw/ tests/
```

## Code Style

We care about more than passing lint. We want GeoClaw to stay small, calm, and readable.

When contributing, please aim for code that feels:

- Simple: prefer the smallest change that solves the real problem
- Clear: optimize for the next reader, not for cleverness
- Decoupled: keep boundaries clean and avoid unnecessary new abstractions
- Honest: do not hide complexity, but do not create extra complexity either
- Durable: choose solutions that are easy to maintain, test, and extend

In practice:

- Line length: 100 characters (`ruff`)
- Target: Python 3.11+
- Linting: `ruff` with rules E, F, I, N, W (E501 ignored)
- Async: uses `asyncio` throughout; pytest with `asyncio_mode = "auto"`
- Prefer readable code over magical code
- Prefer focused patches over broad rewrites
- If a new abstraction is introduced, it should clearly reduce complexity rather than move it around

## Questions?

If you have questions, ideas, or half-formed insights, you are warmly welcome here.

Please feel free to open an issue, join the community, or simply reach out:

- [Discord](https://discord.gg/MnCvHqpUGB)
- [Feishu/WeChat](./COMMUNICATION.md)
- Email: Xubin Ren (@Re-bin) — <xubinrencs@gmail.com>

Thank you for spending your time and care on GeoClaw. At the same time, please remember that part of this repository is an inherited nanobot runtime, so some contributions may naturally touch both layers.
