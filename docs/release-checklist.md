# Release Checklist

> Steps to validate before tagging a new release.

## Pre-Release

- [ ] All CI jobs pass (`make ci` locally, green on GitHub Actions)
- [ ] `make lint` — zero warnings
- [ ] `make typecheck` — zero errors
- [ ] `make test-cov` — coverage ≥ 85%
- [ ] `make prompt-check` — prompt manifest verified
- [ ] `python scripts/check_imports.py` — import boundaries pass
- [ ] `make memory-eval` — review trend (advisory, non-blocking)

## Changelog

- [ ] Update `CHANGELOG.md` — move `[Unreleased]` items under new version heading
- [ ] Bump version in `pyproject.toml`
- [ ] Commit: `chore: release vX.Y.Z`

## Tagging

- [ ] `git tag vX.Y.Z`
- [ ] `git push origin main --tags`

## Post-Release

- [ ] Verify GitHub Actions runs clean on the tag
- [ ] Verify Docker image built and pushed to GHCR
- [ ] Verify staging auto-deployed successfully (check `staging.nanobot.internal`)
- [ ] Deploy to production: Actions → Deploy Production → Run workflow with tag `vX.Y.Z`
- [ ] Verify production health: `curl http://127.0.0.1:18790/health`
- [ ] Add `[Unreleased]` section back to `CHANGELOG.md`
- [ ] Announce release (if applicable)

## Hotfix Process

1. Branch from the release tag: `git checkout -b hotfix/vX.Y.Z+1 vX.Y.Z`
2. Apply fix with test
3. Run full `make ci`
4. Merge to main, tag, release
