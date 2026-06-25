# Contributing to blackcat

Thank you for being here.

blackcat is built with a simple belief: good tools should feel calm, clear, and humane.
We care deeply about useful features, but we also believe in achieving more with less:
solutions should be powerful without becoming heavy, and ambitious without becoming
needlessly complicated.

This guide is not only about how to open a PR. It is also about how we hope to build
software together: with care, clarity, and respect for the next person reading the code.

## Maintainers

Maintainers are community stewards who help review, organize, and maintain the project. The list below describes each maintainer's current open-source project responsibilities.

| Maintainer | Role |
|------------|------|
| [@re-bin](https://github.com/re-bin) | Project lead; reviews community PRs and handles merges |
| [@chengyongru](https://github.com/chengyongru) | Reviews community PRs and may approve them; merges are handled by the project lead |

## Contribution Flow

### What Should I Open a PR For?

PRs are welcome for:

- New features or functionality
- Bug fixes with no behavior changes
- Documentation improvements
- Minor tweaks that don't affect functionality
- Refactoring that is clearly scoped and easy to review
- Changes to APIs or configuration, when the impact is documented

For riskier or larger changes, please open an issue or draft PR early so the
shape of the work can be discussed before the implementation grows too large.

### Starting Work

Before making changes, sync your local checkout and create a topic branch.

```bash
git fetch upstream
git switch main
git pull --ff-only upstream main
git switch -c your-topic-branch
```

Use your primary HKUDS/blackcat remote in place of `upstream` if your checkout
uses a different remote name.

Keep unrelated local changes out of the topic branch. If your checkout already has
work in progress, use a separate worktree or finish that work before starting a
new branch.

## Development Setup

Keep setup boring and reliable. The goal is to get you into the code quickly:

```bash
# Clone the repository
git clone https://github.com/HKUDS/blackcat.git
cd blackcat

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint code
ruff check blackcat/

# Format code — optional. The existing tree predates `ruff format`,
# so running it broadly produces large unrelated diffs.
# Do not mix mechanical formatting churn into a functional PR.
# Use formatting only for the exact code your change intentionally touches.
ruff format <files-you-changed>
```

## Contribution License

By submitting a contribution, you confirm that you have the right to submit it
and agree that it will be licensed under the project's MIT License.

## Code Style

We care about more than passing lint. We want blackcat to stay small, calm, and readable.

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
- Do not mix mechanical formatting, line wrapping, import sorting, or quote churn
  into a feature or bugfix PR. If formatting cleanup is needed, make it a
  separate formatting-only PR.
- If a new abstraction is introduced, it should clearly reduce complexity rather than move it around

## Modifying CI Workflows

If your PR touches `.github/workflows/`, please keep the CI within
GitHub Actions' free tier:

- Use only standard GitHub-hosted runners (`ubuntu-latest`, `windows-latest`)
- Avoid macOS runners, larger runners (`*-cores`, `*-xlarge`, `*-gpu`),
  and self-hosted runners
- Avoid uploading large artifacts or using long retention
- Avoid paid Marketplace actions

If your change genuinely needs to step outside this, please call it out
explicitly in the PR description so it can be discussed before merge.

## Questions?

If you have questions, ideas, or half-formed insights, you are warmly welcome here.

Please feel free to open an [issue](https://github.com/HKUDS/blackcat/issues), join the community, or simply reach out:

- [Discord](https://discord.gg/MnCvHqpUGB)
- [Feishu/WeChat](./COMMUNICATION.md)
- Email: Xubin Ren (@Re-bin) — <xubinrencs@gmail.com>

Thank you for spending your time and care on blackcat. We would love for more people to participate in this community, and we genuinely welcome contributions of all sizes.
