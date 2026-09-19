# Contributing to nanobot

Thank you for being here.

nanobot is built with a simple belief: good tools should feel calm, clear, and humane.
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

Use your primary HKUDS/nanobot remote in place of `upstream` if your checkout
uses a different remote name.

Keep unrelated local changes out of the topic branch. If your checkout already has
work in progress, use a separate worktree or finish that work before starting a
new branch.

## Development Setup

Keep setup boring and reliable. The goal is to get you into the code quickly:

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

# Format code — optional. The existing tree predates `ruff format`,
# so running it broadly produces large unrelated diffs.
# Do not mix mechanical formatting churn into a functional PR.
# Use formatting only for the exact code your change intentionally touches.
ruff format <files-you-changed>
```

### Strict Type Checking

Strict type checking covers optional providers and channels. Reproduce the CI environment
with the same dependency sources and commands:

```bash
uv sync --all-extras --dev
uv run --no-sync python -m scripts.install_channel_dependencies --all-channels
uv run --no-sync basedpyright
```

Keep `--no-sync` on the final commands: channel dependencies come from their package
manifests and are installed explicitly by the setup step.

## Contribution License

By submitting a contribution, you confirm that you have the right to submit it
and agree that it will be licensed under the project's MIT License.

## Code Style

We care about more than passing lint. We want nanobot to stay small, calm, and readable.

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

## Release Packaging Contract

Use the [release checklist](./docs/releasing.md) for candidate preparation, package checks,
documentation coordination, and the final publication handoff.

A stable install must never combine Python from one version with a TUI from another. Publish in
this order:

1. Before pushing a tag, set the package version, verify the exact candidate, build the source
   distribution, all five platform wheels and TUI archives, and review licenses, source offer, and relinking
   materials. Obtain the maintainer's source-offer commitment before publication.
2. Merge the release preparation, verify that its packaged sources match the checked candidate,
   then publish the matching GitHub release tag (`vX.Y.Z`). Recheck any changed sources first.
3. Attach the preverified TUI archives and checksums to the matching GitHub Release. Alternatively,
   manually run **Publish Terminal UI** for the exact tag with the compliance review confirmed;
   reverify its outputs, since a rebuild does not preserve the preflight artifact hashes.
4. Verify every platform archive and checksum is publicly downloadable for fallback/source-built
   installations, then publish the same `X.Y.Z` source distribution and five platform wheels to PyPI.

Each platform wheel contains the built WebUI and the matching native TUI. Pip chooses the wheel
for the user's machine; launching the installed TUI must work without a GitHub download or Bun.
The universal wheel produced by `uv build` is only an intermediate: use
`scripts/build_tui_wheels.py` as described in the checklist, and do not upload that intermediate.
The source distribution remains platform-neutral and does not bundle native binaries.
Keep the platform-specific release archives for fallback/source-built installations. Both the
wheel's `nanobot/tui/bin/` bundle and its matching archive must contain the executable,
target-specific third-party notices, project and runtime licenses, corresponding application
source, a written source offer, relinking instructions, and a checksum manifest. Never upload a
naked TUI executable. Review the minimum OS, libc, architecture and runtime CPU requirements
when changing Bun/OpenTUI; never apply portable platform tags without checking their binaries.
Source checkouts use an editable Python install, run `tui/` with Bun, and
rebuild stale `webui/` assets locally.

The confirmation is an operational commitment, not a cosmetic checkbox. Before accepting it,
verify that the exact Bun/WebKit revisions remain retrievable and that the project can honor the
archive's corresponding-source offer for its full stated period. Preserve published archives and
their source materials.

## Questions?

If you have questions, ideas, or half-formed insights, you are warmly welcome here.

Please feel free to open an [issue](https://github.com/HKUDS/nanobot/issues), join the community, or simply reach out:

- [Discord](https://discord.gg/MnCvHqpUGB)
- [Feishu/WeChat](./COMMUNICATION.md)
- Email: Xubin Ren (@Re-bin) — <xubinrencs@gmail.com>

Thank you for spending your time and care on nanobot. We would love for more people to participate in this community, and we genuinely welcome contributions of all sizes.
