# Branch Protection Rules

> Apply these settings in **GitHub → Settings → Branches → Branch protection rules** for `main`.

## Required Settings

### 1. Require status checks to pass before merging

Enable **Require status checks to pass before merging** and mark these as required:

| CI Job | What it enforces |
|---|---|
| `lint` | Ruff lint + format check |
| `typecheck` | mypy type checking |
| `import-check` | Module boundary enforcement (`scripts/check_imports.py`) |
| `prompt-manifest` | Prompt asset integrity (`scripts/check_prompt_manifest.py`) |
| `test (3.10)` | Tests + coverage ≥ 85% on Python 3.10 |
| `test (3.11)` | Tests + coverage ≥ 85% on Python 3.11 |
| `test (3.12)` | Tests + coverage ≥ 85% on Python 3.12 |

Also enable **Require branches to be up to date before merging**.

#### Informational (non-blocking) checks

| CI Job | What it enforces |
|---|---|
| `memory-eval` | Memory retrieval benchmark trend (`memory-eval-trend.yml`). Runs on PRs touching `nanobot/agent/**` and related paths. Not required for merge — regressions should be reviewed but are not blocking. |

### 2. Require pull request reviews before merging

- **Required number of approvals**: 1
- Enable **Dismiss stale pull request approvals when new commits are pushed**
- Enable **Require review from Code Owners** (uses `.github/CODEOWNERS`)

### 3. Restrict direct pushes

- Enable **Do not allow bypassing the above settings**
- No direct pushes to `main` — all changes go through pull requests

### 4. Additional protections

- Enable **Require linear history** (encourages squash/rebase over merge commits)
- Enable **Include administrators** so even admins follow the rules

## Rationale

These rules ensure:
- **Architecture cannot be accidentally broken** — import boundaries are enforced per PR.
- **Type safety is maintained** — mypy catches regressions before merge.
- **Test coverage cannot degrade** — 85% threshold enforced in CI.
- **Prompt changes are intentional** — manifest verification catches accidental modifications.
- **Code review prevents drift** — at least one reviewer sees every change.

## Local Pre-flight

Before pushing, run the full CI suite locally:

```bash
make ci    # lint + typecheck + import-check + prompt-check + test-cov
```

Or the lighter check (no coverage):

```bash
make check  # lint + typecheck + import-check + prompt-check + test
```
