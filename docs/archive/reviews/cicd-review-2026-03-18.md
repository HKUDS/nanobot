# CI/CD & Operational Review — Nanobot Agent Framework

**Date**: 2026-03-18
**Reviewer**: DevOps Engineering
**Scope**: `.github/workflows/`, `Makefile`, `Dockerfile`, `docker-compose.yml`, `deploy/`,
`pyproject.toml`, `.gitignore`, `CLAUDE.md`, `docs/branch-protection.md`,
`docs/release-checklist.md`

---

## Executive Summary

The nanobot CI/CD pipeline is well-structured for a project of this size. All the
foundational gates exist: lint, typecheck, multi-Python matrix tests, import-boundary
enforcement, container scanning, CodeQL, and Dependabot. The deployment story is
clean — distinct staging and production environments, automatic rollback on health-check
failure, and a manual approval gate for production.

Seven findings require attention before the next production release. The most urgent is a
**volume mount path mismatch** that silently breaks the container config path when running
as a non-root user (finding CI-1). A secondary critical gap is the **build-push workflow
running before CI passes** (finding CI-2), which allows a broken image to reach staging.

---

## Findings

### CI-1 — Volume Mount Path Mismatch (Critical)

**Files**: `Dockerfile`, `deploy/staging/docker-compose.yml`,
`deploy/production/docker-compose.yml`, `docker-compose.yml`

**Description**: The Dockerfile creates a non-root user `nanobot` with `HOME=/home/nanobot`
and prepares `/home/nanobot/.nanobot` as the config directory. The config loader
(`nanobot/config/loader.py` line 11) resolves the config path via `Path.home()`, which
evaluates to `/home/nanobot/.nanobot/config.json` at runtime. However, all three Compose
files mount the host config directory to `/root/.nanobot`:

```yaml
# deploy/production/docker-compose.yml line 26
- ${NANOBOT_CONFIG_DIR:-~/.nanobot}:/root/.nanobot
```

Because the container runs as UID 1001 (`nanobot`), `Path.home()` returns
`/home/nanobot`, not `/root`. The volume content is mounted at `/root/.nanobot` but the
process reads from `/home/nanobot/.nanobot`. The result is that the container starts with
an empty config — silently using defaults rather than the operator's `config.json`. API
keys, channel tokens, and feature flags configured in the host file are invisible to the
running process unless overridden via environment variables.

**Operational risk**: High. In practice the system appears to work only because operators
configure everything through `NANOBOT_*` environment variables in the `.env` file. If
any operator relies on the mounted `config.json` file, those settings are silently
ignored. This is also a config-integrity risk: the container's effective config cannot be
audited from the host mount point.

**Recommendation**: Change all Compose volume mounts from `/root/.nanobot` to
`/home/nanobot/.nanobot` to match the actual runtime user home directory:

```yaml
volumes:
  - ${NANOBOT_CONFIG_DIR:-~/.nanobot}:/home/nanobot/.nanobot
```

Alternatively, set `HOME=/home/nanobot` explicitly in the Compose environment block to
make the resolution predictable regardless of shell defaults. Update all three Compose
files: `docker-compose.yml`, `deploy/staging/docker-compose.yml`, and
`deploy/production/docker-compose.yml`.

---

### CI-2 — Build-Push Runs Independently of CI Gate (High)

**Files**: `.github/workflows/build-push.yml`, `.github/workflows/ci.yml`

**Description**: `build-push.yml` is triggered directly on `push: branches: [main]`. It
does not declare `needs:` on the `ci.yml` workflow jobs and has no dependency on CI
passing. This means a commit that breaks tests or type-checking triggers two parallel
workflows: CI (which will fail) and Build-Push (which may succeed and push a broken
image to GHCR). The staging deploy then triggers automatically on the successful
Build-Push completion, deploying the broken image to staging before CI failure surfaces.

**Operational risk**: High. Staging may run code that has not passed the test gate. If the
health check passes (the gateway can start even with logic bugs), staging will run
untested code indefinitely until the next good push. Production is manual-only so it
would not be automatically affected, but operators may deploy from a known-bad tag.

**Recommendation**: Add a `workflow_run` dependency or use a `needs:` cross-workflow
pattern. The cleanest approach with the current architecture is to merge build-push into
a job that runs after the CI jobs in `ci.yml`, using `needs: [lint, typecheck, test, import-check, prompt-manifest]`.
Alternatively, convert `build-push.yml` to trigger on `workflow_run` of the CI workflow
with `types: [completed]` and add a condition checking `conclusion == 'success'`,
mirroring the pattern already used in `deploy-staging.yml`.

---

### CI-3 — No Dependency Lock File (High)

**Files**: `pyproject.toml`, all workflow files

**Description**: There is no `uv.lock`, `requirements.txt` (pinned), or `poetry.lock`
checked into the repository. CI installs dependencies with `pip install -e ".[dev]"` on
every run, resolving to the latest compatible versions within the semver ranges in
`pyproject.toml`. The ranges are reasonably tight (e.g., `litellm>=1.81.5,<2.0.0`), but
a new patch release of any dependency can silently change behavior between CI runs on the
same commit SHA.

**Operational risk**: High. Reproducibility is not guaranteed. A dependency release over
a weekend can cause Monday CI failures unrelated to code changes. More critically, the
Docker image built from the same `Dockerfile` on two different dates may contain
different dependency versions, making the "build once, deploy everywhere" guarantee
unreliable.

**Recommendation**: Generate and commit a `uv.lock` (since the base image already uses
`uv`) or a pinned `requirements.txt`. Update CI to install from the lock file
(`uv sync --frozen` or `pip install -r requirements.lock`). The `build-push.yml` already
uses uv in the base image; aligning the development workflow to use `uv` consistently
and committing `uv.lock` is the lowest-friction fix.

---

### CI-4 — Production .env Contains Default Neo4j Credentials Committed to Repo (High)

**Files**: `deploy/production/.env`, `docker-compose.yml`

**Description**: The committed `deploy/production/.env` file contains:

```
NEO4J_AUTH=neo4j/nanobot_graph
```

This is the same default credential present in `docker-compose.yml` as the fallback
(`${NEO4J_AUTH:-neo4j/nanobot_graph}`). While `.env` files are listed in `.gitignore`
for the root and for `deploy/production/.env`, **the file is committed to the
repository** (confirmed by its presence and readable content). The `.gitignore` entry
only ignores future `.env` files; once a file is tracked, `.gitignore` has no effect.

**Operational risk**: High. Anyone with repository read access can retrieve the Neo4j
password. If this credential is used in a production Neo4j instance without rotation, it
represents an exposed database credential.

**Recommendation**: Remove `deploy/production/.env` from git history using `git
filter-repo` or BFG Repo Cleaner. Replace the committed file with
`deploy/production/.env.example` only (which already exists). Change the Neo4j password
in any running instance. Add a `gitleaks` or `truffleHog` step to the security workflow
to detect future credential commits.

---

### CI-5 — No pip Dependency Caching in CI (Medium)

**Files**: `.github/workflows/ci.yml`, `.github/workflows/security.yml`,
`.github/workflows/memory-eval-trend.yml`

**Description**: Every CI job runs `pip install -e ".[dev]"` without caching. The CI
workflow has five jobs (lint, typecheck, import-check, prompt-manifest, test ×3 matrix),
each installing the full dependency tree independently. With no `actions/cache` or
`setup-python` cache configuration, each job takes approximately 60–90 seconds for
installs on cold runners.

**Operational risk**: Low operationally, but significant developer experience impact. With
five concurrent jobs and a 3-version matrix for tests, the overhead is 7 independent
installs per PR. This adds roughly 5–8 minutes to CI wall-clock time and wastes runner
minutes.

**Recommendation**: Add pip caching via `setup-python`'s built-in cache parameter:

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: '3.11'
    cache: 'pip'
    cache-dependency-path: 'pyproject.toml'
```

This is a one-line addition per job and is the recommended pattern for GitHub Actions.

---

### CI-6 — No Prometheus /metrics Endpoint (Medium)

**Files**: `deploy/prometheus-snippet.yml`, `docs/deployment.md`

**Description**: The `prometheus-snippet.yml` includes a comment acknowledging that
nanobot does not expose a `/metrics` endpoint — Prometheus is instead pointed at
`/health`, which returns a JSON document, not Prometheus-format metrics. The hardening
backlog (`docs/hardening-backlog.md` P1) calls out that the health endpoint should
return per-channel health, memory store health, and provider reachability. The current
health check returns only basic liveness.

**Operational risk**: Medium. Without application-level Prometheus metrics (request
latency, tool execution counts, LLM token usage, error rates), operators are dependent on
Langfuse dashboards for any performance visibility. Langfuse is an external SaaS
dependency — if it is unavailable or misconfigured (the `.env` shows it as optional),
the operator is blind to performance regressions. Container-level cAdvisor metrics exist
but cannot surface business-logic degradation (e.g., increasing tool retry rates or
memory consolidation latency).

**Recommendation**: Implement a `/metrics` endpoint in the gateway using `prometheus_client`
(already a transitive dependency through several packages). Export at minimum:
request count by channel, LLM call duration histogram, tool execution counts by tool
name, and error rates. The Langfuse observability integration can remain as the primary
trace-level system; Prometheus covers aggregate operational metrics. This aligns with the
P1 health-endpoint hardening item.

---

### CI-7 — SECURITY.md Is Stale (Low)

**Files**: `SECURITY.md`

**Description**: `SECURITY.md` shows `Last Updated: 2026-02-03`. It references
`https://github.com/HKUDS/nanobot/security/advisories` (an external organization repo),
which appears to be the upstream origin rather than the current project. The document was
noted as stale in prior review phases (finding D-M3). The policy is substantively
correct, but the stale date and wrong repo URL reduce credibility with external
contributors evaluating the project.

**Operational risk**: Low. No functional impact, but it affects trust and contributor
confidence in the security process.

**Recommendation**: Update the last-updated date, correct the GitHub Security Advisories
URL to point to the actual repository, and consider adding a brief note about the
automated scanning pipeline (pip-audit, Trivy, CodeQL) that now exists.

---

## Strengths

The following areas are well-implemented and do not require immediate action.

**CI gate coverage**: The CI workflow enforces lint (ruff), formatting, type checking
(mypy), import-boundary enforcement, prompt-manifest integrity, and test coverage (85%
gate) across Python 3.10, 3.11, and 3.12. This is comprehensive for a project of this
scope.

**Security scanning pipeline**: pip-audit, Trivy (both image and IaC config scanning),
and CodeQL run on every push and PR, with an additional weekly scheduled scan.
Dependabot covers pip, npm (WhatsApp bridge), and GitHub Actions on a weekly cadence.
The `.trivyignore` file is present and documented with an expected format for accepted
false positives.

**Dockerfile quality**: The image uses a minimal bookworm-slim base, installs runtime
dependencies only, uses a layer-cache-friendly dependency-first build order, creates a
non-root user (UID 1001), sets a dynamic healthcheck via `NANOBOT_GATEWAY__PORT`, and
cleans apt caches. The EXPOSE declaration matches the healthcheck port.

**Deployment script robustness**: `deploy/deploy.sh` uses `set -euo pipefail`, validates
arguments, saves the previous image before deploying, runs a polling health check with
configurable timeout, auto-rolls back to the previous image on health-check failure, and
supports a `--dry-run` flag. This is production-grade shell scripting.

**Container network isolation**: Staging and production Compose files bind ports to
`127.0.0.1` (`127.0.0.1:18791:18791`), preventing direct external access. Traffic is
routed through Caddy (WireGuard-bound). The root development `docker-compose.yml` binds
`18790:18790` without the loopback restriction, which is acceptable for local dev.

**Release process**: The release checklist is thorough and covers pre-release CI
verification, changelog maintenance, tag-based build triggering, post-release
verification across staging and production, and a documented hotfix process. The PR
template includes checklists aligned with the development conventions.

**Pre-commit hooks**: The `.pre-commit-config.yaml` enforces ruff lint, ruff format, mypy
type checking, and import-boundary checking at commit time, catching issues before CI.

**Secret management**: No hardcoded API keys or tokens were found in workflow files or
source code. All sensitive values are either commented out in `.env.example` files or
expected via GitHub Actions secrets / environment variables. The `GITHUB_TOKEN` is used
for GHCR authentication (correct pattern; no PAT required).

**Production environment approval gate**: `deploy-production.yml` uses a GitHub
`environment: production` block, which enforces the required-reviewer approval gate
configured in GitHub Settings before the job runs.

**mypy strictness for core modules**: `disallow_untyped_defs = true` is applied to the
agent core, tool system, config, and errors modules via overrides, with the lenient
default applying only to less critical areas.

---

## Summary Table

| ID   | Finding                                             | Severity | Status   |
|------|-----------------------------------------------------|----------|----------|
| CI-1 | Volume mount path mismatch (root vs nanobot user)   | Critical | Open     |
| CI-2 | Build-push runs before CI gate passes               | High     | Open     |
| CI-3 | No dependency lock file                             | High     | Open     |
| CI-4 | Production .env with Neo4j credentials committed    | High     | Open     |
| CI-5 | No pip dependency caching in CI                     | Medium   | Open     |
| CI-6 | No Prometheus /metrics endpoint                     | Medium   | Open     |
| CI-7 | SECURITY.md stale (date + wrong repo URL)           | Low      | Open     |
| D-M3 | (Prior) SECURITY.md stale                          | Low      | Open     |
