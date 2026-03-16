## Description

<!-- What does this PR do? Link to issue if applicable. -->

Closes #

## Type of Change

- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Refactor (no behavior change, internal restructuring)
- [ ] Documentation (docs, ADRs, comments)
- [ ] CI/tooling (build, test, lint configuration)
- [ ] Breaking change (fix or feature that would break existing functionality)

## Checklist

### Required
- [ ] `make check` passes (lint + typecheck + import-check + prompt-check + test)
- [ ] Tests added or updated for changed behavior
- [ ] No unrelated changes ("while I'm here" changes split to separate PR)
- [ ] Public API preserved (or ADR written if changed)
- [ ] `__all__` updated if new public exports added
- [ ] `python scripts/check_imports.py` — import boundaries respected

### If prompts changed:
- [ ] `python scripts/check_prompt_manifest.py --update` run and manifest committed
- [ ] Prompt regression tests pass (`pytest tests/test_prompt_regression.py`)

### If config/policy changed:
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] `docs/operating-policies.md` updated if defaults changed
- [ ] `docs/feature-flag-governance.md` updated if flag added/removed

### If architectural change:
- [ ] ADR created or updated in `docs/adr/`
- [ ] `docs/architecture.md` updated if module boundaries changed

## Testing

<!-- How was this tested? Which test files cover the change? -->

## Notes for Reviewers

<!-- Anything reviewers should pay special attention to? -->
