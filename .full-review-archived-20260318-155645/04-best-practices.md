# Phase 4: Best Practices & Standards

## Framework & Language Findings (4A)

### High Severity

**[BP-H1] Mixed logging backends — stdlib `logging` mixed with `loguru`**
- Files: `nanobot/agent/tools/registry.py:29`, `nanobot/agent/capability.py:26`, `nanobot/agent/memory/graph.py:49`, `nanobot/agent/memory/reranker.py:22`
- These four files use `import logging; logger = logging.getLogger(__name__)` while the entire rest of the agent layer uses `from loguru import logger`. The project's `LogConfig` in `schema.py` configures loguru sinks; stdlib `logging` calls will not flow through them unless an `InterceptHandler` is wired (it is not). Structured JSON log output is silently broken for tool-registry, capability, graph, and reranker events.
- Fix: One-line change per file — replace `import logging; logger = logging.getLogger(__name__)` with `from loguru import logger`.

---

### Medium Severity

**[BP-M1] `FailureClass(str, Enum)` vs `StrEnum` — Python version target mismatch**
- Files: `loop.py:198`, `nanobot/agent/memory/ontology_types.py:32,112`
- `pyproject.toml` has three conflicting Python version targets: `requires-python = ">=3.10"`, ruff `target-version = "py311"`, mypy `python_version = "3.10"`. Ruff allows `py311`-only syntax (like `StrEnum`) that mypy won't verify for 3.10 and that fails at runtime on 3.10. The `(str, Enum)` pattern is the correct 3.10-compatible spelling, but the mixed version targets mean this situation is neither enforced nor documented as deliberate.
- Fix: Align all three to the same floor. If 3.10 support is still required: set ruff `target-version = "py310"`. If dropping 3.10: update `requires-python = ">=3.11"` and migrate to `StrEnum`.

**[BP-M2] `on_progress` callback type is inconsistent across the call chain**
- Files: `loop.py:794,858` vs `loop.py:1876,2263`
- `_call_llm` and `_run_agent_loop` annotate `on_progress: Callable[..., Awaitable[None]] | None`; `_process_message` and `process_direct` use `Callable[[str], Awaitable[None]] | None`. The actual `_bus_progress` closure takes `content: str` plus several keyword-only arguments. Neither annotation is accurate; type checking on the callback is entirely bypassed.
- Fix: Define a `ProgressCallback` `Protocol` matching the real signature and use it consistently across all four sites.

**[BP-M3] `asyncio.create_task` self-discard inside `finally` is fragile — use `add_done_callback`**
- File: `loop.py:2018–2030`
- The `_consolidate_and_unlock` nested coroutine removes itself from `_consolidation_tasks` inside its own `finally` block via `asyncio.current_task()`. The standard pattern is `.add_done_callback(self._consolidation_tasks.discard)` on the returned task. Additionally, the nested coroutine closes over `self`, `session`, and `lock` and produces an opaque `repr` in debugging — extracting it to a private method `_run_consolidation_task(session, lock)` would improve both observability and testability.
- Fix:
  ```python
  _task = asyncio.create_task(self._run_consolidation_task(session, lock))
  self._consolidation_tasks.add(_task)
  _task.add_done_callback(self._consolidation_tasks.discard)
  ```

**[BP-M4] Redundant `@pytest.mark.asyncio` on 311 test functions across 54 files**
- `pyproject.toml` sets `asyncio_mode = "auto"`, which makes `@pytest.mark.asyncio` a no-op on every `async def test_*` function. 311 redundant decorators remain. This creates a latent inconsistency: if `asyncio_mode` is ever changed to `"strict"`, the tests' behavior changes without any code change.
- Fix: Remove all `@pytest.mark.asyncio` decorators (safe with `auto` mode), or switch to `asyncio_mode = "strict"` for explicit opt-in (requires keeping the decorators).

---

### Low Severity

**[BP-L1] `from __future__ import annotations` missing from `context.py`**
- File: `nanobot/agent/context.py:1`
- CLAUDE.md mandates "Every module starts with `from __future__ import annotations`". This is the only file in `nanobot/agent/` that violates this rule.
- Fix: Add `from __future__ import annotations` as the first non-comment line.

**[BP-L2] `ToolCallTracker` class constants missing `ClassVar[int]` annotation**
- File: `loop.py:235–237` — `WARN_THRESHOLD`, `REMOVE_THRESHOLD`, `GLOBAL_BUDGET` declared without type annotations. Should be `ClassVar[int]`.

**[BP-L3] Bare `list[dict]` in six signatures instead of `list[dict[str, Any]]`**
- File: `loop.py:792,857,859,1392,1393,2224` — inconsistent with all other usages in the same file.

**[BP-L4] `set[asyncio.Task]` missing generic parameter `[None]`**
- File: `loop.py:467` — should be `set[asyncio.Task[None]]`. `mission.py:130` correctly uses `dict[str, asyncio.Task[None]]`.

**[BP-L5] `_consolidate_memory` has an untyped `session` parameter**
- File: `loop.py:2246` — only untyped parameter in the file; should be `session: Session`.

**[BP-L6] `RuntimeError` used in `delegation.py` instead of typed `NanobotError`**
- File: `delegation.py:542` — `raise RuntimeError("Coordinator not available for delegation")`. A typed subclass of `NanobotError` would allow the error-handling path to make smarter recovery decisions.

**[BP-L7] `ruff>=0.1.0` has no upper bound in dev dependencies**
- File: `pyproject.toml:71` — diverges from the pre-commit pinned version (`v0.9.10`). Risk of linting drift between environments.

**[BP-L8] `TYPE_CHECKING` guard for `ExecToolConfig` duplicated by a runtime import in `__init__`**
- File: `loop.py:104,354` — with `from __future__ import annotations`, the `TYPE_CHECKING` guard is sufficient for annotation use; the runtime import at line 354 exists only for the `ExecToolConfig()` default instantiation call and is therefore correct, but the duplication is misleading.

---

## CI/CD & DevOps Findings (4B)

### High Severity

**[OPS-H1] `build-push.yml` triggers without a CI gate — broken builds reach staging**
- The build-push workflow fires on every push to `main` and triggers `deploy-staging.yml` on success. Neither workflow declares `needs:` on the `ci.yml` jobs. A commit that fails lint, typecheck, or tests can still produce a published Docker image automatically deployed to staging.
- Fix: Add `ci.yml` jobs as required branch protection checks on `main` in GitHub Settings, or restructure into a single workflow with `needs: [lint, typecheck, test]` before the build step.

**[OPS-H2] `deploy/production/.env` is tracked in git**
- File: `/home/carlos/nanobot/deploy/production/.env` exists in the repo and is not in `.gitignore`. Currently contains only commented-out lines, but establishes a pattern where a developer could commit real credentials here with those credentials being preserved in git history permanently.
- Fix: Add `deploy/production/.env` and `deploy/staging/.env` to `.gitignore` immediately. Rename the tracked file to `.env.example` (a `.env.example` already exists alongside it).

**[OPS-H3] Production deployment has no CI or staging soak gate**
- `deploy-production.yml` triggers only on `workflow_dispatch` with no required checks. A developer can manually deploy any image tag to production — including one that failed health checks in staging.
- Fix: Add GitHub environment protection rules (required reviewers, required status checks) on the `production` environment. Document a minimum staging soak period in the deployment runbook.

---

### Medium Severity

**[OPS-M1] Trivy security scans use `exit-code: '0'` — never block CI**
- File: `.github/workflows/security.yml` — both `trivy-image` and `trivy-config` jobs report findings but never fail the pipeline, even for CRITICAL/HIGH severity CVEs.
- Fix: Set `exit-code: '1'` for both jobs. Add `trivyignore` suppression file for known accepted false positives.

**[OPS-M2] `trivy-action@master` — unpinned action tag (supply chain risk)**
- Fix: Pin to a specific release tag or commit SHA, e.g. `aquasecurity/trivy-action@v0.20.0`.

**[OPS-M3] Hardcoded Neo4j password in developer `docker-compose.yml`**
- `NEO4J_AUTH: neo4j/nanobot_graph` is hardcoded. The production Compose already uses an env-var pattern (`${NEO4J_AUTH:-neo4j/nanobot_graph}`).
- Fix: Apply the same pattern to the root-level `docker-compose.yml`.

**[OPS-M4] `network_mode: host` in both staging and production Compose files**
- Both deploy configs use `network_mode: host`, removing network isolation between the container and the host. If the agent is compromised via tool execution, it has broader lateral movement opportunities.
- Fix: Use a named Docker network with explicit port bindings (`ports: ["127.0.0.1:18790:18790"]`).

**[OPS-M5] mypy `disallow_untyped_defs = false` globally — `loop.py` not covered**
- The most complex async code in the project (`loop.py`) is not under strict mypy checking. The module-level override only enforces strict defs for `nanobot.errors`, `nanobot.config.*`, and `nanobot.agent.tools.base`.
- Fix: Incrementally expand the `disallow_untyped_defs = true` override to cover `nanobot.agent.*` module by module.

**[OPS-M6] Consolidation task exceptions silently swallowed**
- File: `loop.py:2029–2030` — `asyncio.create_task(_consolidate_and_unlock())` has no `.add_done_callback` to surface exceptions. Failed consolidation is invisible in logs.
- Fix:
  ```python
  _task.add_done_callback(
      lambda t: logger.exception("Consolidation task failed") if t.exception() else None
  )
  ```

**[OPS-M7] No alerting rules or on-call runbook**
- A `deploy/prometheus-snippet.yml` exists but is not integrated. No Prometheus alert on `nanobot_health_status != "ok"`, no runbook.
- Fix: Expand the health response to include per-channel status; add a Prometheus alert rule; document a runbook in `docs/`.

**[OPS-M8] Dockerfile ships Python 3.10; CI tests 3.10/3.11/3.12 — version divergence**
- `FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim` always produces a 3.10 image. Code that passes the 3.11/3.12 CI matrix may have different runtime behavior on the 3.10 production image.
- Fix: Pin the production image to the most-tested CI version (3.11 or 3.12), or build and test the Docker image against the same matrix.

---

### Low Severity

**[OPS-L1] No SAST step (bandit) in CI**
- CodeQL and Trivy are present but bandit's Python-specific checks (`subprocess.shell=True`, hardcoded passwords, weak crypto) complement CodeQL.
- Fix: Add `bandit -r nanobot/ -ll` to `security.yml`.

**[OPS-L2] Pre-commit does not run mypy or import-check**
- `.pre-commit-config.yaml` runs ruff and file hygiene only. Module-boundary violations and type errors are only caught in CI.
- Fix: Add mypy and the import-check script to pre-commit hooks.

**[OPS-L3] No per-test timeout configured**
- No `pytest-timeout` in dev dependencies; individual hung tests consume the full 15-minute CI job budget.
- Fix: Add `pytest-timeout` and set `timeout = 30` in `[tool.pytest.ini_options]`.

**[OPS-L4] No test parallelisation**
- `pytest-xdist` is absent; tests run serially. Will become a bottleneck as the suite grows.
- Fix: Add `pytest-xdist` to dev dependencies; add `-n auto` in CI.

**[OPS-L5] Rollback state file not durable across host rebuilds**
- `deploy.sh` stores the previous image tag in `deploy/<env>/.deploy-state/previous-image` on the host filesystem. A host rebuild silently disables rollback.
- Fix: Store the previous tag in a GitHub environment variable or a Docker volume that persists across host rebuilds.

**[OPS-L6] `EH-L1` — Crash-barrier logs `str(e)` without traceback**
- File: `loop.py:1573` — `logger.error("Error processing message: {}", e)` loses the stack trace. Change to `logger.exception("Error processing message")`.

**[OPS-L7] `~/.nanobot` config directory not mentioned in `.gitignore`**
- Low risk (it's a home-directory path), but worth documenting explicitly given the SM-H2 pattern of `.env` drift.
