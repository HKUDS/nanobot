# Evidence

Task id: `crm-ai-analysis-layer`

## 2026-05-07 - Task 1: Confirm Nanobot extension points

TDD cycle:

- Failing check command: `python3 - <<'PY' ... PY`
- Failing check result: failed with `FileNotFoundError` because `.dek/changes/crm-opportunity-intelligence/EXTENSION_POINTS.md` did not exist yet.
- Minimal implementation: created `.dek/changes/crm-opportunity-intelligence/EXTENSION_POINTS.md` documenting CLI, tools/MCP, skills, DingTalk, message delivery, memory safety, tests, Docker smoke, and `.dek` runtime boundary.
- First passing attempt result: failed with `AssertionError` because the required phrase `production runtime must not depend on `.dek`` was case-sensitive and the file used `Production runtime`.
- Minimal fix: changed the phrase to exactly `production runtime must not depend on `.dek``.
- Passing check command: `python3 - <<'PY' ... PY`
- Passing check result: command exited successfully with no assertion output.

Verification command used:

```bash
python3 - <<'PY'
from pathlib import Path
p = Path('.dek/changes/crm-opportunity-intelligence/EXTENSION_POINTS.md')
text = p.read_text()
required = ['nanobot/cli/commands.py', 'nanobot/agent/tools', 'nanobot/skills', 'nanobot/channels/dingtalk.py', 'nanobot/agent/tools/message.py', 'nanobot/agent/memory.py', 'Dockerfile', 'docker-compose.yml', '.dek']
missing = [item for item in required if item not in text]
assert not missing, missing
assert 'must not be placed in `nanobot/channels/dingtalk.py`' in text
assert 'production runtime must not depend on `.dek`' in text
PY
```

Files changed:

- `.dek/changes/crm-opportunity-intelligence/EXTENSION_POINTS.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- No runtime code was changed in this task.
- No real CRM adapter was implemented or accessed.
- No Docker production configuration was changed.

## 2026-05-07 - Task 2: Define standard CRM data model

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_models.py`
- Failing test result: failed with `ModuleNotFoundError: No module named 'nanobot.crm'`, confirming the model package did not exist.
- Minimal implementation: created `nanobot/crm/__init__.py` and `nanobot/crm/models.py` with v1 domain dataclasses for report request/window/scope, source references, opportunity records, metric records, unavailable metrics, evidence traces, and report output.
- Passing test command: `uv run --extra dev pytest tests/crm/test_models.py`
- Passing test result: `8 passed in 0.16s`.
- Lint command: `uv run --extra dev ruff check nanobot/crm tests/crm/test_models.py`
- Lint result: `All checks passed!`

Files changed:

- `nanobot/crm/__init__.py`
- `nanobot/crm/models.py`
- `tests/crm/test_models.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- Model definitions are intentionally narrow and do not include real CRM adapter behavior.
- No real CRM data, credentials, or Docker production configuration were accessed or changed.

## 2026-05-07 - Task 3: Create mock CRM fixture

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_fixtures.py`
- Failing test result: failed with `ModuleNotFoundError: No module named 'tests.crm.fixtures'`, confirming synthetic fixtures did not exist.
- Minimal implementation: created `tests/crm/fixtures.py` with labeled synthetic fixture scenarios for daily, weekly, dashboard, empty-data, missing-input, and multi-sales-user cases.
- Passing test command: `uv run --extra dev pytest tests/crm/test_fixtures.py`
- Passing test result: `5 passed in 0.16s` after lint fix.
- Initial lint command: `uv run --extra dev ruff check tests/crm/fixtures.py tests/crm/test_fixtures.py`
- Initial lint result: failed with two import ordering issues.
- Lint fix command: `uv run --extra dev ruff check --fix tests/crm/fixtures.py tests/crm/test_fixtures.py`
- Final lint command: `uv run --extra dev ruff check tests/crm/fixtures.py tests/crm/test_fixtures.py`
- Final lint result: `All checks passed!`

Files changed:

- `tests/crm/fixtures.py`
- `tests/crm/test_fixtures.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- Fixtures are synthetic test data only.
- No real CRM data, `.env*`, credentials, or Docker production configuration were accessed or changed.

## 2026-05-07 - Task 4: Create CRMAdapter interface

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_adapters.py`
- Failing test result: failed with `ModuleNotFoundError: No module named 'nanobot.crm.adapters'`, confirming the adapter boundary did not exist.
- Minimal implementation: created `nanobot/crm/adapters.py` with read-only `CRMAdapter` protocol, `read_opportunities` method, stable `CRMAdapterErrorCode`, and sanitized `CRMAdapterError`.
- Passing test command: `uv run --extra dev pytest tests/crm/test_adapters.py`
- Passing test result: `4 passed in 0.19s`.
- Lint command: `uv run --extra dev ruff check nanobot/crm/adapters.py tests/crm/test_adapters.py`
- Lint result: `All checks passed!`

Files changed:

- `nanobot/crm/adapters.py`
- `tests/crm/test_adapters.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- No mock adapter or real CRM adapter implementation exists yet.
- No real CRM data, credentials, or Docker production configuration were accessed or changed.

## 2026-05-07 - Task 5: Implement MockCRMAdapter

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_mock_adapter.py tests/crm/test_adapters.py`
- Failing test result: failed with `ModuleNotFoundError: No module named 'nanobot.crm.mock_adapter'`, confirming the mock adapter did not exist.
- Minimal implementation: created `nanobot/crm/mock_adapter.py` with read-only `MockCRMAdapter.read_opportunities` filtering synthetic fixture records by report window and owner scope.
- Passing test command: `uv run --extra dev pytest tests/crm/test_mock_adapter.py tests/crm/test_adapters.py`
- Passing test result: `9 passed in 0.20s` after lint fix.
- Initial lint command: `uv run --extra dev ruff check nanobot/crm/mock_adapter.py tests/crm/test_mock_adapter.py`
- Initial lint result: failed with one import ordering issue.
- Lint fix command: `uv run --extra dev ruff check --fix tests/crm/test_mock_adapter.py`
- Final lint command: `uv run --extra dev ruff check nanobot/crm/mock_adapter.py tests/crm/test_mock_adapter.py`
- Final lint result: `All checks passed!`

Files changed:

- `nanobot/crm/mock_adapter.py`
- `tests/crm/test_mock_adapter.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- Mock adapter uses synthetic fixtures only.
- No real CRM adapter, credentials, or Docker production configuration were accessed or changed.

## 2026-05-07 - Task 6: Implement pipeline metrics

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_metrics_daily.py tests/crm/test_metrics_weekly.py tests/crm/test_metrics_dashboard.py tests/crm/test_metrics_missing_inputs.py`
- Failing test result: failed with `ModuleNotFoundError: No module named 'nanobot.crm.metrics'`, confirming the metrics layer did not exist.
- Minimal implementation: created `nanobot/crm/metrics.py` with deterministic `compute_pipeline_metrics` for opportunity count, pipeline total amount, stage/status/owner counts, and unavailable amount metric markers.
- Passing test command: `uv run --extra dev pytest tests/crm/test_metrics_daily.py tests/crm/test_metrics_weekly.py tests/crm/test_metrics_dashboard.py tests/crm/test_metrics_missing_inputs.py`
- Passing test result: `6 passed in 0.15s` after lint fix.
- Initial lint command: `uv run --extra dev ruff check nanobot/crm/metrics.py tests/crm/test_metrics_daily.py tests/crm/test_metrics_weekly.py tests/crm/test_metrics_dashboard.py tests/crm/test_metrics_missing_inputs.py`
- Initial lint result: failed with one import ordering issue in `tests/crm/test_metrics_missing_inputs.py`.
- Lint fix command: `uv run --extra dev ruff check --fix tests/crm/test_metrics_missing_inputs.py`
- Final lint command: `uv run --extra dev ruff check nanobot/crm/metrics.py tests/crm/test_metrics_daily.py tests/crm/test_metrics_weekly.py tests/crm/test_metrics_dashboard.py tests/crm/test_metrics_missing_inputs.py`
- Final lint result: `All checks passed!`

Files changed:

- `nanobot/crm/metrics.py`
- `tests/crm/test_metrics_daily.py`
- `tests/crm/test_metrics_weekly.py`
- `tests/crm/test_metrics_dashboard.py`
- `tests/crm/test_metrics_missing_inputs.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- Metrics are intentionally minimal and cover only the current synthetic v1 cases.
- No report formatting, LLM narrative, real CRM adapter, credentials, or Docker production configuration were added.

## 2026-05-07 - Task 7: Implement daily report

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_report_daily.py`
- Failing test result: failed with `ModuleNotFoundError: No module named 'nanobot.crm.reports'`, confirming the report assembly module did not exist.
- Minimal implementation: created `nanobot/crm/reports.py` with `generate_daily_report`, request validation before adapter read, deterministic metrics rendering, no-data output, and evidence placeholder section.
- Passing test command: `uv run --extra dev pytest tests/crm/test_report_daily.py`
- Passing test result: `3 passed in 0.17s`.
- Lint command: `uv run --extra dev ruff check nanobot/crm/reports.py tests/crm/test_report_daily.py`
- Lint result: `All checks passed!`

Files changed:

- `nanobot/crm/reports.py`
- `tests/crm/test_report_daily.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- Evidence traces are placeholders until task 13.
- No weekly/dashboard report, LLM narrative, real CRM adapter, credentials, or Docker production configuration were added.

## 2026-05-07 - Task 8: Implement weekly report

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_report_weekly.py tests/crm/test_report_daily.py`
- Failing test result: failed with `ImportError: cannot import name 'generate_weekly_report'`, confirming weekly report assembly was missing.
- Minimal implementation: added `generate_weekly_report` to `nanobot/crm/reports.py` with fixed weekly sections, validation before adapter read, deterministic metric rendering, and no trend claims without metric support.
- Passing test command: `uv run --extra dev pytest tests/crm/test_report_weekly.py tests/crm/test_report_daily.py`
- Passing test result: `6 passed in 0.20s`.
- Lint command: `uv run --extra dev ruff check nanobot/crm/reports.py tests/crm/test_report_weekly.py`
- Lint result: `All checks passed!`

Files changed:

- `nanobot/crm/reports.py`
- `tests/crm/test_report_weekly.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- Evidence traces are placeholders until task 13.
- No dashboard report, DingTalk output, real CRM adapter, credentials, or Docker production configuration were added.

## 2026-05-07 - Task 9: Implement dashboard summary

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_report_dashboard.py tests/crm/test_report_daily.py tests/crm/test_report_weekly.py`
- Failing test result: failed with `ImportError: cannot import name 'generate_dashboard_summary'`, confirming dashboard summary assembly was missing.
- Minimal implementation: added `generate_dashboard_summary` to `nanobot/crm/reports.py` with fixed dashboard sections, deterministic metrics, and no complex BI controls.
- Passing test command: `uv run --extra dev pytest tests/crm/test_report_dashboard.py tests/crm/test_report_daily.py tests/crm/test_report_weekly.py`
- Passing test result: `8 passed in 0.20s`.
- Lint command: `uv run --extra dev ruff check nanobot/crm/reports.py tests/crm/test_report_dashboard.py`
- Lint result: `All checks passed!`

Files changed:

- `nanobot/crm/reports.py`
- `tests/crm/test_report_dashboard.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- Evidence traces are placeholders until task 13.
- No CLI, DingTalk output, real CRM adapter, credentials, or Docker production configuration were added.

## 2026-05-07 - Task 10: Implement CLI

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/cli/test_crm_cli.py`
- Failing test result: failed with exit code `2` for CRM report commands because the `crm` command group did not exist.
- Minimal implementation: added `nanobot/crm/cli.py` and wired a thin `crm report` Typer group in `nanobot/cli/commands.py` for daily, weekly, and dashboard mock-mode report generation.
- Passing CLI test command: `uv run --extra dev pytest tests/cli/test_crm_cli.py`
- Passing CLI test result: `4 passed in 0.31s` after lint fixes.
- Report regression command: `uv run --extra dev pytest tests/crm/test_report_daily.py tests/crm/test_report_weekly.py tests/crm/test_report_dashboard.py`
- Report regression result: `8 passed in 0.21s`.
- Initial lint command: `uv run --extra dev ruff check nanobot/crm/cli.py nanobot/cli/commands.py tests/cli/test_crm_cli.py`
- Initial lint result: failed with existing `E402` import placement errors in `nanobot/cli/commands.py`, one unused local logger import, and import ordering in `tests/cli/test_crm_cli.py`.
- Minimal lint fixes: added file-level `# ruff: noqa: E402` to preserve the existing Windows stdout setup import pattern, removed redundant local `from loguru import logger`, and ran import sorting on the new CLI test file.
- Final lint command: `uv run --extra dev ruff check nanobot/crm/cli.py nanobot/cli/commands.py tests/cli/test_crm_cli.py`
- Final lint result: `All checks passed!`

Files changed:

- `nanobot/crm/cli.py`
- `nanobot/cli/commands.py`
- `tests/cli/test_crm_cli.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- CLI supports mock adapter mode only.
- Evidence traces are placeholders until task 13.
- No DingTalk command, real CRM adapter, credentials, or Docker production configuration were added.

## 2026-05-07 - Task 11: Connect Nanobot tool/skill

Decision:

- User selected option 2: do not register a native built-in CRM tool now; a CRM MCP server will be built later.
- Task 11 therefore skipped `nanobot/agent/loop.py` and `nanobot/agent/tools/crm.py` changes and implemented the skill/MCP-first path only.

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/agent/test_crm_skill.py`
- Failing test result: failed with `FileNotFoundError` because `nanobot/skills/crm-opportunity-intelligence/SKILL.md` did not exist.
- Minimal implementation: created `nanobot/skills/crm-opportunity-intelligence/SKILL.md` documenting MCP server usage, deterministic metrics, evidence traces, no CRM writeback, synthetic/mock development data, and no native tool registration in `nanobot/agent/loop.py`.
- First passing attempt result: two tests passed and one failed on exact wording for `do not register a native built-in CRM tool`.
- Minimal fix: adjusted the skill wording to match the non-core registration requirement and ran import sorting on the new test file.
- Passing test command: `uv run --extra dev pytest tests/agent/test_crm_skill.py`
- Passing test result: `3 passed in 0.01s`.
- Lint command: `uv run --extra dev ruff check tests/agent/test_crm_skill.py`
- Lint result: `All checks passed!`

Files changed:

- `nanobot/skills/crm-opportunity-intelligence/SKILL.md`
- `tests/agent/test_crm_skill.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- No CRM MCP server exists yet.
- No native CRM tool is registered in `AgentLoop`.
- No real CRM data, credentials, or Docker production configuration were accessed or changed.

## 2026-05-07 - Task 12: Implement DingTalk fixed command

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/command/test_crm_dingtalk_command.py tests/channels/test_crm_dingtalk_delivery.py`
- Failing test result: five tests failed because `/crm-daily`, `/crm-weekly`, and `/crm-dashboard` were not dispatchable and returned `None`.
- Minimal implementation: added fixed CRM command specs and prefix handlers in `nanobot/command/builtin.py` for synthetic daily, weekly, and dashboard report output, using existing `OutboundMessage` delivery shape and `nanobot.crm.cli` helpers.
- Passing command test: `uv run --extra dev pytest tests/command/test_crm_dingtalk_command.py tests/channels/test_crm_dingtalk_delivery.py`
- Passing command result: `6 passed in 0.21s`.
- DingTalk transport regression command: `uv run --extra dev pytest tests/channels/test_dingtalk_channel.py`
- DingTalk transport regression result: `20 passed in 8.07s`.
- Lint command: `uv run --extra dev ruff check nanobot/command/builtin.py nanobot/command/router.py tests/command/test_crm_dingtalk_command.py tests/channels/test_crm_dingtalk_delivery.py`
- Lint result: `All checks passed!`

Files changed:

- `nanobot/command/builtin.py`
- `tests/command/test_crm_dingtalk_command.py`
- `tests/channels/test_crm_dingtalk_delivery.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- DingTalk fixed commands use synthetic/mock report generation only.
- Evidence traces are placeholders until task 13.
- No DingTalk transport code, real CRM adapter, credentials, or Docker production configuration were changed.

## 2026-05-07 - Task 13: Implement evidence trace

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_evidence.py tests/crm/test_report_daily.py tests/crm/test_report_weekly.py tests/crm/test_report_dashboard.py`
- Failing test result: failed with `ModuleNotFoundError: No module named 'nanobot.crm.evidence'`, confirming the evidence trace builder did not exist.
- Minimal implementation: created `nanobot/crm/evidence.py` with deterministic trace ids and attached report-local evidence traces to daily, weekly, and dashboard outputs.
- Passing evidence command: `uv run --extra dev pytest tests/crm/test_evidence.py tests/crm/test_report_daily.py tests/crm/test_report_weekly.py tests/crm/test_report_dashboard.py`
- Passing evidence result: `10 passed in 0.20s`.
- Lint command: `uv run --extra dev ruff check nanobot/crm/evidence.py nanobot/crm/reports.py tests/crm/test_evidence.py`
- Lint result: `All checks passed!`
- Full CRM regression before real adapter: `uv run --extra dev pytest tests/crm`
- Full CRM regression result: `38 passed in 0.17s`.

Files changed:

- `nanobot/crm/evidence.py`
- `nanobot/crm/reports.py`
- `tests/crm/test_evidence.py`
- `tests/crm/test_report_daily.py`
- `tests/crm/test_report_weekly.py`
- `tests/crm/test_report_dashboard.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- Evidence traces are deterministic and report-local, but still backed only by synthetic/mock data.
- No real CRM adapter, credentials, or Docker production configuration were accessed or changed.

Final verification before stopping at Task 14:

- Command: `uv run --extra dev pytest tests/crm tests/cli/test_crm_cli.py tests/agent/test_crm_skill.py tests/command/test_crm_dingtalk_command.py tests/channels/test_crm_dingtalk_delivery.py`
- Initial result: failed because two tests still expected the pre-task-13 placeholder `evidence pending` after evidence traces were implemented.
- Fix: updated `tests/cli/test_crm_cli.py` and `tests/command/test_crm_dingtalk_command.py` to assert `trace-pipeline-total-amount-v1`.
- Re-run result: `51 passed in 0.30s`.
- Lint command: `uv run --extra dev ruff check nanobot/crm tests/crm tests/cli/test_crm_cli.py tests/agent/test_crm_skill.py tests/command/test_crm_dingtalk_command.py tests/channels/test_crm_dingtalk_delivery.py nanobot/command/builtin.py nanobot/command/router.py nanobot/cli/commands.py`
- Lint result: `All checks passed!`

Stop reason:

- Task 14 `Implement RealCRMAdapter` requires user confirmation of the real CRM read interface, allowed entity/field contract, and stable source reference format.
- No real CRM access was attempted.

## 2026-05-07 - Task 15: Docker smoke test

TDD cycle:

- Failing smoke test command: `uv run --extra dev pytest tests/docker/test_crm_docker_smoke.py`
- Failing smoke test result: two failures. Runtime CRM code imported `tests.crm.fixtures`, while the Docker image only copies `nanobot/`; `.dockerignore` also did not exclude `.dek`, `.env*`, or `.env.nanobot`.
- Minimal implementation: moved synthetic CRM scenarios into runtime-safe `nanobot/crm/synthetic_data.py`, kept `tests/crm/fixtures.py` as a thin test compatibility wrapper, updated `nanobot/crm/cli.py` and `nanobot/crm/mock_adapter.py` to avoid `tests.*` imports, and added `.dek`, `.dek/`, `.env*`, and `.env.nanobot` to `.dockerignore`.
- Passing smoke test command: `uv run --extra dev pytest tests/docker/test_crm_docker_smoke.py`
- Passing smoke test result after synthetic-data and ignore updates: `2 passed in 0.01s`.
- Additional failing check: `docker run --rm nanobot-crm-smoke nanobot crm report daily --adapter mock --date 2026-01-15 --scope synthetic-team`
- Additional failing result: failed with `No such command 'nanobot'` because the image entrypoint already executes `nanobot`, so the documented command became `nanobot nanobot crm ...`.
- Minimal implementation: added an entrypoint guard that strips an optional leading `nanobot` argument before executing the CLI.
- Passing entrypoint smoke test command: `uv run --extra dev pytest tests/docker/test_crm_docker_smoke.py`
- Passing entrypoint smoke test result: `3 passed in 0.01s`.

Verification commands:

```bash
uv run --extra dev pytest tests/crm tests/cli/test_crm_cli.py tests/agent/test_crm_skill.py tests/command/test_crm_dingtalk_command.py tests/channels/test_crm_dingtalk_delivery.py tests/docker/test_crm_docker_smoke.py
uv run --extra dev ruff check nanobot/crm tests/crm tests/cli/test_crm_cli.py tests/agent/test_crm_skill.py tests/command/test_crm_dingtalk_command.py tests/channels/test_crm_dingtalk_delivery.py tests/docker/test_crm_docker_smoke.py nanobot/command/builtin.py nanobot/command/router.py nanobot/cli/commands.py
docker compose config
docker build -t nanobot-crm-smoke .
docker run --rm nanobot-crm-smoke nanobot crm report daily --adapter mock --date 2026-01-15 --scope synthetic-team
docker run --rm nanobot-crm-smoke crm report daily --adapter mock --date 2026-01-15 --scope synthetic-team
```

Verification results:

- Full CRM feature test result: `54 passed in 0.38s`.
- Full CRM feature lint result: `All checks passed!`.
- `docker compose config` exited successfully. Note: Docker Compose expanded values from `env_file` into command output; those values are intentionally not copied into this evidence file.
- `docker build -t nanobot-crm-smoke .` completed successfully.
- `docker run --rm nanobot-crm-smoke nanobot crm report daily --adapter mock --date 2026-01-15 --scope synthetic-team` completed successfully and printed the synthetic `Sales Daily Report` with `pipeline_total_amount: 20000.00` and `trace-pipeline-total-amount-v1-002`.
- `docker run --rm nanobot-crm-smoke crm report daily --adapter mock --date 2026-01-15 --scope synthetic-team` also completed successfully.

Files changed:

- `.dockerignore`
- `entrypoint.sh`
- `nanobot/crm/cli.py`
- `nanobot/crm/mock_adapter.py`
- `nanobot/crm/synthetic_data.py`
- `tests/crm/fixtures.py`
- `tests/docker/test_crm_docker_smoke.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`

Remaining gaps:

- Docker smoke uses synthetic/mock CRM data only.
- Task 14 real CRM adapter remains deferred pending user confirmation of the real CRM read interface and field/source-reference contract.
- `docker compose config` can expose `env_file` values in terminal output; future smoke automation should prefer sanitized config inspection when secrets may be present.

## 2026-05-07 - Task 14A: Extract GraphQL read contract

Scope:

- This round only read `/Users/yang/Desktop/CRM_schema.md` and updated documentation/planning artifacts.
- No real CRM endpoint was accessed.
- `.env.nanobot` was not read.
- No token, secret, webhook, robot URL, or real CRM business/customer data was requested or copied into `.dek` or docs.
- `RealCRMAdapter` was not implemented.
- DingTalk integration was not changed.

Schema facts recorded:

- Endpoint: `http://api.in.chaitin.net/crm/query`, evidenced by `/Users/yang/Desktop/CRM_schema.md:10`.
- Root `Query`: evidenced by `/Users/yang/Desktop/CRM_schema.md:13-19`.
- Root `Mutation`: evidenced by `/Users/yang/Desktop/CRM_schema.md:13-17` and `/Users/yang/Desktop/CRM_schema.md:498`.
- V1 query allow-list exists in the schema: `listUser`, `listReport`, `listCompany`, `companyInfo`, `listProject`, `projectInfo`, `reportInfo`, `listActivity`, `reportRelatedInfo`, `list_business_chance`, and `business_chance`, evidenced by `/Users/yang/Desktop/CRM_schema.md:42`, `44`, `78`, `91`, `105`, `127`, `165`, `169`, `175`, `213`, and `215`.
- Mutation fields are numerous and include write-like operations, evidenced by `/Users/yang/Desktop/CRM_schema.md:498-617`; v1 must explicitly prohibit all Mutation usage.

Files changed:

- `docs/crm-graphql-contract.md`
- `.dek/changes/crm-opportunity-intelligence/TASKS.md`
- `.dek/tasks/crm-ai-analysis-layer/FACTS.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Verification:

- Initial documentation verification command failed because the assertion expected `.env.nanobot was not read` without Markdown backticks, while the evidence intentionally used backticks around `.env.nanobot`.
- Re-run documentation verification command passed with no assertion output after checking for the exact Markdown phrase `` `.env.nanobot` was not read ``.

## 2026-05-07 - Task 14B: Extend normalized models for GraphQL-backed CRM data

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_models.py`
- Failing test result: failed during collection with `ImportError: cannot import name 'ActivityRecord' from 'nanobot.crm.models'`, confirming the GraphQL-backed normalized record models did not exist yet.
- Minimal implementation: extended `OpportunityRecord` with optional `owner_name`, `customer_id`, and `customer_name`, and added frozen dataclasses `ActivityRecord`, `ReportRecord`, `CustomerRecord`, `BusinessChanceRecord`, and `SalesRepRecord` to `nanobot/crm/models.py`.
- Passing test command: `uv run --extra dev pytest tests/crm/test_models.py`
- Passing test result: `16 passed in 0.18s` before lint fix, then `16 passed in 0.16s` after import sorting.
- Required lint command: `uv run --extra dev ruff check nanobot/crm/models.py tests/crm/test_models.py`
- Initial lint result: failed only for import ordering in `tests/crm/test_models.py`.
- Lint fix command: `uv run --extra dev ruff check --fix tests/crm/test_models.py`
- Final lint result: `All checks passed!`.

Scope confirmations:

- No `real_adapter.py` was created or modified.
- No GraphQL HTTP client was implemented.
- No real CRM endpoint was accessed.
- `.env.nanobot` was not read.
- No Mutation behavior was implemented.
- No `httpx`, DingTalk, provider, CLI, MCP, or real CRM client imports were added to `nanobot/crm/models.py`.
- Source reference tests use synthetic ids and avoid token/secret markers.

Files changed:

- `nanobot/crm/models.py`
- `tests/crm/test_models.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Remaining gaps:

- 14B only defines normalized data containers; it does not parse GraphQL payloads, normalize Money scalars, paginate connections, or call the CRM endpoint.
- 14C remains the next task for a GraphQL client shell with mocked transport.

## 2026-05-07 - Task 14C: Implement GraphQL client shell with mocked transport

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_graphql_client.py`
- Failing test result: failed during collection with `ModuleNotFoundError: No module named 'nanobot.crm.graphql_client'`, confirming the GraphQL client shell did not exist yet.
- Minimal implementation: created `nanobot/crm/graphql_client.py` with `CRMGraphQLClient`, `CRMGraphQLClientError`, `GraphQLTransport`, and `DEFAULT_ALLOWED_OPERATIONS`. The client accepts injected transport, forwards endpoint/token/operation/query/variables, rejects unknown operations, rejects mutation operation strings before transport execution, maps GraphQL and transport errors to sanitized adapter-compatible error codes, and redacts the configured token from error messages.
- Passing test command: `uv run --extra dev pytest tests/crm/test_graphql_client.py`
- Passing test result: `9 passed in 0.24s` before lint fix, then `9 passed in 0.20s` after removing unused imports.
- Required lint command: `uv run --extra dev ruff check nanobot/crm/graphql_client.py tests/crm/test_graphql_client.py`
- Initial lint result: failed only for unused `Any` imports in the new client and test files.
- Lint fix command: `uv run --extra dev ruff check --fix nanobot/crm/graphql_client.py tests/crm/test_graphql_client.py`
- Final lint result: `All checks passed!`.
- Regression command: `uv run --extra dev pytest tests/crm/test_models.py tests/crm/test_graphql_client.py`
- Regression result: `25 passed in 0.16s`.

Scope confirmations:

- Tests use `FakeTransport`; no real CRM endpoint was accessed.
- No `httpx`, `requests`, or real HTTP transport was implemented.
- `.env.nanobot` was not read.
- No real token was used; tests use a fake token and assert it is absent from exception string/repr.
- No `RealCRMAdapter` was implemented.
- No Mutation behavior was implemented; mutation operation strings are rejected before transport execution.

Files changed:

- `nanobot/crm/graphql_client.py`
- `tests/crm/test_graphql_client.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Remaining gaps:

- The client shell has no built-in real HTTP transport by design; real adapter work must continue to use mocked transport until explicitly approved otherwise.
- 14D remains the next task for `RealCRMAdapter` using mocked GraphQL responses only.

## 2026-05-07 - Task 14D: Implement RealCRMAdapter with mocked GraphQL responses

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_redaction.py tests/crm`
- Failing test result: failed during collection with `ModuleNotFoundError: No module named 'nanobot.crm.real_adapter'`, confirming `RealCRMAdapter` did not exist yet.
- Minimal implementation: added `nanobot/crm/real_adapter.py` with synchronous `RealCRMAdapter` using injected `CRMGraphQLClient`, normalized mocked `listProject`, `listActivity`, `listReport`, `listCompany`, and `list_business_chance` responses into standard records, and extended `CRMAdapter` protocol with read-only methods for activities, reports, customers, and business chances.
- First implementation test result: failed during collection because `def _read_connection[T]` used Python 3.12 generic function syntax, while the project runs Python 3.11.
- Syntax fix: replaced PEP 695 method syntax with a Python 3.11-compatible `TypeVar` signature.
- Second implementation test result: one redaction test failed because GraphQL error handling included the full error object and leaked a synthetic raw payload marker from `extensions`.
- Redaction fix: changed `CRMGraphQLClient` error formatting to surface only sanitized GraphQL error messages and omit extensions/raw payload fields.
- Passing required test command: `uv run --extra dev pytest tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_redaction.py tests/crm`
- Passing required test result: `66 passed in 0.24s`.
- Required lint command: `uv run --extra dev ruff check nanobot/crm tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_redaction.py`
- Initial lint result: failed only for an unused `Any` import in `nanobot/crm/real_adapter.py`.
- Lint fix command: `uv run --extra dev ruff check --fix nanobot/crm/real_adapter.py`
- Final lint result: `All checks passed!`.

Scope confirmations:

- All tests use synthetic mocked GraphQL responses and injected fake transports.
- No real CRM endpoint was accessed.
- `.env.nanobot` was not read.
- No real token or customer data was used.
- No DingTalk code was changed.
- No Mutation operation or writeback method was implemented.
- Adapter tests assert no create/update/delete/assign/contact/message/task/writeback methods exist on `RealCRMAdapter`.
- Error tests assert sanitized exceptions do not include the fake credential, Authorization header text, or raw payload marker.

Files changed:

- `nanobot/crm/adapters.py`
- `nanobot/crm/graphql_client.py`
- `nanobot/crm/real_adapter.py`
- `tests/crm/test_adapters.py`
- `tests/crm/test_real_adapter_contract.py`
- `tests/crm/test_real_adapter_redaction.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Remaining gaps:

- `RealCRMAdapter` is tested only with mocked GraphQL responses; it still has no real HTTP transport and no approved real CRM smoke path.
- Money scalar parsing supports synthetic `{"value": "..."}` shape and simple scalar values; the real CRM `Money` JSON shape remains an open question.
- Task 14E remains for additional redaction and forbidden mutation hardening.

### 2026-05-07 00:00

Claim: Current CRM GraphQL client and RealCRMAdapter only allow v1 allow-listed Query operations, reject Mutation and unknown operations before transport execution, expose no writeback methods, do not read `.env.nanobot`, and do not leak token, Authorization header text, raw CRM payload, or secret text through errors, logs, exceptions, or this evidence.

Verdict: VERIFIED

Commands:

- `uv run --extra dev pytest tests/crm/test_graphql_client.py` — initially failed after adding missing client-level Authorization-header redaction assertions, then passed after tightening redaction.
- `uv run --extra dev pytest tests/crm/test_graphql_client.py tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_redaction.py tests/crm/test_adapters.py` — passed, `24 passed in 0.22s`.
- `uv run --extra dev ruff check nanobot/crm tests/crm/test_graphql_client.py tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_redaction.py tests/crm/test_adapters.py` — passed, `All checks passed!`.
- `uv run --extra dev pytest tests/crm` — passed, `66 passed in 0.22s`.
- `grep` checks via tool over `nanobot/crm` and `tests/crm` — confirmed runtime CRM code has no real HTTP/env endpoint imports or hardcoded CRM endpoint; remaining runtime matches are mutation rejection logic and redaction labels only.

Evidence:

- Mutation rejection: `tests/crm/test_graphql_client.py` covers direct mutation operation and allow-listed operation name with mutation query string; transport call list remains empty.
- Unknown operation rejection: `tests/crm/test_graphql_client.py` covers `unknownQuery`; transport call list remains empty.
- Writeback methods absent: `tests/crm/test_real_adapter_contract.py` checks `RealCRMAdapter` public names for create/update/delete/assign/contact/message/task/write fragments; `tests/crm/test_adapters.py` checks the protocol exposes read methods only.
- Token and Authorization redaction: added assertions in `tests/crm/test_graphql_client.py`; `tests/crm/test_real_adapter_redaction.py` covers adapter-level unavailable and unauthorized errors.
- Raw payload redaction: `tests/crm/test_real_adapter_redaction.py` verifies GraphQL error extensions raw payload marker is absent from adapter errors; `tests/crm/test_real_adapter_contract.py` verifies missing-field errors do not include synthetic raw payload ids.
- `.env.nanobot` non-read boundary: source tests assert `nanobot/crm/graphql_client.py` and `nanobot/crm/real_adapter.py` do not import env-reading modules and do not contain `.env` references.

Reasoning:

Focused tests exercise the smallest local surface that can disprove the claim: the client validation path, injected transport path, adapter public API, adapter/client error handling, and source-level no-env/no-real-endpoint guards. A missing client-level Authorization-label redaction assertion initially failed, proving the check was meaningful; after tightening `CRMGraphQLClient._redact`, the focused and full CRM suites pass. No real CRM endpoint, real token, `.env.nanobot`, or raw CRM data was used.

Gaps:

- This verifies local mocked-transport behavior only; no real CRM smoke is approved or executed.
- This does not prove external callers will never log caught exceptions elsewhere; it verifies the exceptions raised by the CRM client/adapter are sanitized before leaving this boundary.

### 2026-05-07 00:00

Claim: With locally provided read-only CRM GraphQL endpoint/token, `RealCRMAdapter` can execute the allow-listed `listProject` query with pagination limit `1`, normalize at most one record, avoid Mutation, avoid secret leakage, and output only record count, record type, redacted source reference, and adapter status.

Verdict: INCONCLUSIVE

Commands:

- `python3 - <<'PY' ... PY` — inconclusive before CRM access because the system Python environment lacked `tomllib` required by Nanobot imports.
- `uv run python - <<'PY' ... PY` — inconclusive; command completed with sanitized output only: adapter status `INCONCLUSIVE`, record count `0`, record type `none`, redacted source reference `none`.

Evidence:

- Operation name: `listProject`.
- Pagination limit: `1` configured through `RealCRMAdapter(page_limit=1)`.
- Output surface: sanitized command printed only adapter status, record count, record type, and redacted source reference.
- Mutation: no Mutation operation was constructed or executed; the smoke used `RealCRMAdapter.read_opportunities`, which calls allow-listed `listProject` through `CRMGraphQLClient`.
- Secret handling: no token, Authorization header, endpoint value, raw GraphQL response, customer detail, amount, contact, phone, or email was printed or written to evidence.

Reasoning:

The real smoke did not produce a normalized record, so the positive adapter claim cannot be verified. The sanitized command intentionally collapses missing runtime config, endpoint reachability, authorization, response-shape, and empty-result failures into `INCONCLUSIVE` to avoid leaking endpoint/token/raw CRM details. Because no record was returned, this is not evidence that real CRM normalization works; it only confirms the smoke command preserved the output/redaction boundary.

Gaps:

- The exact reason for `INCONCLUSIVE` was not recorded to avoid exposing sensitive runtime or CRM details.
- No real CRM record normalization was proven.
- Do not proceed to broader real smoke based on this result.

### 2026-05-07 00:00

Claim: The previous optional real CRM smoke returned `INCONCLUSIVE`; sanitized diagnostics can identify which layer failed without printing endpoint, token, Authorization header, raw GraphQL response, customer/project names, amount, contacts, phone, or email.

Verdict: VERIFIED

Commands:

- `uv run --extra dev pytest tests/crm/test_real_smoke_diagnostics.py` — initially failed because the first diagnostics implementation returned the more precise `unauthorized_or_forbidden` category while the test expected generic `graphql_error`; test expectation was corrected.
- `uv run --extra dev pytest tests/crm/test_real_smoke_diagnostics.py tests/crm/test_graphql_client.py tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_redaction.py` — passed, `26 passed in 0.17s`.
- `uv run --extra dev ruff check nanobot/crm tests/crm/test_real_smoke_diagnostics.py tests/crm/test_graphql_client.py tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_redaction.py` — passed, `All checks passed!`.
- `uv run python - <<'PY' ... PY` sanitized real diagnostics — completed with allowed diagnostic fields only.

Sanitized diagnostics summary:

- endpoint_present: `false`
- token_present: `false`
- operation_name: `listProject`
- mutation_used: `false`
- limit: `1`
- http_reached: `false`
- http_status_category: `not_attempted`
- graphql_errors_count: `0`
- graphql_error_categories: `()`
- top_level_field_present: `false`
- connection_present: `false`
- connection_total_present: `false`
- data_count: `0`
- first_record_field_presence: all tracked fields `false`
- normalized_count: `0`
- normalization_error_category: `none`
- root_cause_category: `config_missing`

Reasoning:

The diagnostics reached the config-presence layer and stopped before HTTP because the tool process environment did not contain the expected CRM GraphQL endpoint/token variables. Therefore the previous `INCONCLUSIVE` result is explained by `config_missing` in this execution context, not by network reachability, authorization, GraphQL errors, empty data, missing required fields, or normalization. The diagnostics code and tests verify that fake tokens, raw responses, customer/project names, and amount-like values are not emitted by diagnostics.

Gaps:

- This does not prove the user's interactive shell lacks config; it proves this OpenCode tool process did not receive the required environment variables.
- No HTTP request was attempted in this diagnostic run.
- No real CRM record normalization was tested.

## 2026-05-07 - Documentation convergence audit for MCP route

- Did documentation audit over the requested ranges: `.dek/project/`, `.dek/changes/crm-opportunity-intelligence/`, `.dek/tasks/crm-ai-analysis-layer/`, `docs/`, and `nanobot/skills/crm-opportunity-intelligence/SKILL.md`.
- Created `docs/crm/DOCS_INVENTORY.md` classifying CRM-related documents and task artifacts for the move from Nanobot internal `RealCRMAdapter` direct GraphQL access to a separate read-only CRM MCP Server.
- Did not delete files.
- Did not move files.
- Did not change business code.
- Did not implement an MCP server.
- Did not access real CRM.
- Did not read `.env.nanobot`.
- Did not read or output token, secret, or real CRM data.

## 2026-05-07 - Canonical CRM docs convergence

- Created canonical CRM documentation directory entries: `docs/crm/README.md`, `docs/crm/GRAPHQL_CONTRACT.md`, `docs/crm/MCP_SERVER_DESIGN.md`, `docs/crm/MCP_TOOL_CONTRACT.md`, `docs/crm/MANUAL_TEST.md`, and `docs/crm/MIGRATION_NOTES.md`.
- Migrated and reorganized the old GraphQL contract content into `docs/crm/GRAPHQL_CONTRACT.md` for the future CRM MCP Server boundary.
- Added the requested supersession notice to the top of `docs/crm-graphql-contract.md` and kept the old file in place for migration review.
- Updated `docs/crm/DOCS_INVENTORY.md`, `PROGRESS.md`, and `HANDOFF.md` to point future work at canonical `docs/crm/` docs.
- Did not delete files.
- Did not move files.
- Did not change business code.
- Did not implement an MCP server.
- Did not access real CRM.
- Did not read `.env.nanobot`.
- Did not read or output token, secret, endpoint auth header, or real CRM data.

## 2026-05-07 - MCP-first architecture and task update

- Updated `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` to state that real CRM GraphQL access is handled by an independent CRM MCP Server.
- Updated `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` to state Nanobot retains `nanobot/crm/models.py`, `nanobot/crm/mock_adapter.py`, `nanobot/crm/metrics.py`, `nanobot/crm/evidence.py`, `nanobot/crm/reports.py`, and mock CLI behavior.
- Updated `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` to state Nanobot should not expand the in-process `RealCRMAdapter` direct GraphQL path for production real CRM access.
- Updated `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` to include future `MCPCRMAdapter` or direct MCP tool usage as the Nanobot-to-CRM-MCP connection layer.
- Updated `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` to assign read-only GraphQL client, Query allow-list, fixed selection sets, forbidden Mutation, pagination, redaction, sanitized diagnostics, and no raw payload logging to the CRM MCP Server.
- Updated `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` to mark DingTalk deferred, CRM writeback out of scope, and real CRM smoke allowed only through `crm_smoke_check` or equivalent read-only MCP tool.
- Updated `.dek/changes/crm-opportunity-intelligence/TASKS.md` to preserve old task history while marking the direct in-process GraphQL client/`RealCRMAdapter` route as superseded for production.
- Updated `.dek/changes/crm-opportunity-intelligence/TASKS.md` with future MCP-first tasks 15A through 15J.
- Updated `PROGRESS.md` and `HANDOFF.md` with the MCP-first architecture/task status.
- Did not delete files.
- Did not move files.
- Did not change business code.
- Did not implement an MCP server.
- Did not access real CRM.
- Did not read `.env.nanobot`.
- Did not read or output token, secret, endpoint auth header, or real CRM data.

## 2026-05-07 - Manual test Compose safety correction

- Updated `docs/crm/MANUAL_TEST.md` Docker Mock Smoke optional Compose syntax check from plain `docker compose config` to `docker compose config --quiet`.
- Documented that plain `docker compose config` can only be used when it is confirmed not to print secrets from `.env.nanobot` or other environment sources; otherwise it must not be run.
- Documented that Compose-expanded environment output must not be written into docs, `.dek`, logs, memory, or chat.
- Did not delete files.
- Did not move files.
- Did not change business code.
- Did not implement an MCP server.
- Did not access real CRM.
- Did not read `.env.nanobot`.
- Did not read or output token, secret, endpoint auth header, or real CRM data.

## 2026-05-07 - Task 15B: Create MCP server skeleton with no real CRM access

TDD cycle:

- Failing test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Failing test result: `6 failed` with `ModuleNotFoundError` for `crm_mcp_server.contract` and `crm_mcp_server.server`, confirming the package skeleton did not exist yet.
- Minimal implementation: created independent `crm_mcp_server/` package skeleton with static metadata, v1 read-only tool names, runtime defaults disabling real CRM access, and tests for no write-like tools.
- First implementation test result: still failed with `ModuleNotFoundError` because the independent package directory was not on `sys.path` when tests ran from the repository root.
- Minimal test harness fix: added `crm_mcp_server/tests/conftest.py` to put only the independent package root on `sys.path` for package tests, without wiring it into Nanobot runtime.
- Passing test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Passing test result: `6 passed in 0.01s`.
- Initial lint command: `uv run --extra dev ruff check crm_mcp_server`
- Initial lint result: one import-order issue in `crm_mcp_server/tests/test_forbidden_tools.py`.
- Lint fix command: `uv run --extra dev ruff check --fix crm_mcp_server`
- Final lint command: `uv run --extra dev ruff check crm_mcp_server`
- Final lint result: `All checks passed!`.
- Independent package import check: `uv run python -c "from crm_mcp_server.server import get_server_metadata; data = get_server_metadata(); assert data['real_crm_access_enabled'] is False; assert data['network_enabled'] is False; print(data['name'])"` from `crm_mcp_server/`.
- Independent package import check result: printed `crm-mcp-server`.

Files changed:

- `crm_mcp_server/pyproject.toml`
- `crm_mcp_server/README.md`
- `crm_mcp_server/crm_mcp_server/__init__.py`
- `crm_mcp_server/crm_mcp_server/contract.py`
- `crm_mcp_server/crm_mcp_server/schemas.py`
- `crm_mcp_server/crm_mcp_server/server.py`
- `crm_mcp_server/tests/conftest.py`
- `crm_mcp_server/tests/test_server_skeleton.py`
- `crm_mcp_server/tests/test_forbidden_tools.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Scope confirmations:

- No GraphQL transport was implemented.
- No real CRM endpoint was accessed.
- `.env.nanobot` was not read.
- No token, secret, endpoint auth header, or raw GraphQL payload was added or output.
- No Mutation or write-like MCP tool was implemented.
- No Nanobot config wiring was added.
- No DingTalk integration was added.
- No Nanobot runtime core files were changed.

Remaining gaps:

- 15B is a metadata/tool-contract skeleton only. 15C remains for read-only contract and forbidden mutation tests with mocked transport.

## 2026-05-07 - Task 15C: Implement read-only contract and forbidden mutation tests

TDD cycle:

- Failing test command: `uv run --extra dev pytest crm_mcp_server/tests/test_read_contract.py crm_mcp_server/tests/test_forbidden_mutation.py`
- Failing test result: `9 failed` with missing `V1_ALLOWED_QUERY_NAMES` / `list_v1_query_names` and `ModuleNotFoundError: No module named 'crm_mcp_server.graphql'`, confirming the read-only GraphQL contract did not exist yet.
- Minimal implementation: added the canonical v1 Query allow-list to `crm_mcp_server/crm_mcp_server/contract.py` and added `crm_mcp_server/crm_mcp_server/graphql.py` with `ReadOperation`, `GraphQLContractError`, fixed selection-set operation construction, mutation rejection, write-like operation-name rejection, and read query text validation.
- First passing focused command: `uv run --extra dev pytest crm_mcp_server/tests/test_read_contract.py crm_mcp_server/tests/test_forbidden_mutation.py`
- First passing focused result: `9 passed in 0.01s`.
- Full test command before lint fix: `uv run --extra dev pytest crm_mcp_server/tests`
- Full test result before lint fix: `15 passed in 0.02s`.
- Initial lint command: `uv run --extra dev ruff check crm_mcp_server/crm_mcp_server/contract.py crm_mcp_server/crm_mcp_server/graphql.py crm_mcp_server/tests/test_read_contract.py crm_mcp_server/tests/test_forbidden_mutation.py`
- Initial lint result: failed with import-order issues in the two new test files.
- Lint fix command: `uv run --extra dev ruff check --fix crm_mcp_server/tests/test_read_contract.py crm_mcp_server/tests/test_forbidden_mutation.py`
- Additional contract tightening: removed the public `query_override` parameter from `build_read_operation` so callers cannot supply raw arbitrary GraphQL text; mutation text validation remains available through `validate_read_query_text` without transport execution.

Final verification:

- Test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Test result: `15 passed in 0.02s`.
- Lint command: `uv run --extra dev ruff check crm_mcp_server/crm_mcp_server/contract.py crm_mcp_server/crm_mcp_server/graphql.py crm_mcp_server/tests/test_read_contract.py crm_mcp_server/tests/test_forbidden_mutation.py`
- Lint result: `All checks passed!`.
- Safety assertion command: `PYTHONPATH=crm_mcp_server uv run --extra dev python - <<'PY' ... PY`
- Safety assertion result: `15C safety assertions passed`.

Files changed:

- `crm_mcp_server/crm_mcp_server/contract.py`
- `crm_mcp_server/crm_mcp_server/graphql.py`
- `crm_mcp_server/tests/test_read_contract.py`
- `crm_mcp_server/tests/test_forbidden_mutation.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Scope confirmations:

- Query allow-list matches `docs/crm/GRAPHQL_CONTRACT.md`: `listReport`, `reportInfo`, `reportRelatedInfo`, `listProject`, `projectInfo`, `listActivity`, `listCompany`, `companyInfo`, `listUser`, `list_business_chance`, and `business_chance`.
- Allow-listed Query operations can be constructed with fixed selection sets.
- Unknown operations are rejected before any transport behavior.
- Operation type `mutation` is rejected.
- Query text containing a `mutation` operation token is rejected.
- Write-like operation names are rejected.
- No public `run_graphql`, `execute_query`, `execute_graphql`, `raw_query`, `query`, or `query_override` passthrough surface is exposed for operation construction.
- Fixed selection-set tests assert sensitive contact fragments such as phone, email, address, contact, and attachment are omitted from company detail selections.
- No real HTTP transport was implemented.
- No real CRM endpoint was accessed.
- `.env.nanobot` was not read.
- No token, secret, endpoint auth header, or raw GraphQL payload was added or output.
- No Nanobot config wiring, DingTalk integration, or Nanobot runtime core change was added.

Remaining gaps:

- 15C only builds and validates read-only GraphQL operations; it still does not execute transport.
- 15D remains the next task for `crm_smoke_check` with mocked transport only.

## 2026-05-07 - Task 15D: Implement `crm_smoke_check` with mocked transport

TDD cycle:

- Failing test command: `uv run --extra dev pytest crm_mcp_server/tests/test_smoke_check.py`
- Failing test result: `7 failed`; `crm_smoke_check` was not in `list_v1_tools()` and `crm_mcp_server.diagnostics` did not exist, confirming the diagnostic tool path was absent.
- Minimal implementation: added `crm_smoke_check` to the read-only MCP tool contract, added `crm_mcp_server/crm_mcp_server/diagnostics.py` with `MockGraphQLTransport` and sanitized `crm_smoke_check`, and documented the new tool output in `docs/crm/MCP_TOOL_CONTRACT.md`.
- Focused passing command: `uv run --extra dev pytest crm_mcp_server/tests/test_smoke_check.py`
- Focused passing result: `7 passed in 0.01s`.
- First full test command: `uv run --extra dev pytest crm_mcp_server/tests`
- First full test result: `1 failed, 21 passed` because the older 15B `test_forbidden_tools.py` exact tool-list assertion did not yet include `crm_smoke_check`.
- Minimal regression fix: updated `crm_mcp_server/tests/test_forbidden_tools.py` to include `crm_smoke_check` in `V1_READ_ONLY_TOOL_NAMES`.

Final verification:

- Test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Test result: `22 passed in 0.02s`.
- Lint command: `uv run --extra dev ruff check crm_mcp_server/crm_mcp_server/contract.py crm_mcp_server/crm_mcp_server/server.py crm_mcp_server/crm_mcp_server/diagnostics.py crm_mcp_server/tests/test_smoke_check.py crm_mcp_server/tests/test_forbidden_tools.py docs/crm/MCP_TOOL_CONTRACT.md`
- Lint result: `All checks passed!`.
- Safety assertion command: `PYTHONPATH=crm_mcp_server uv run --extra dev python - <<'PY' ... PY`
- Safety assertion result: `15D safety assertions passed`.

Files changed:

- `crm_mcp_server/crm_mcp_server/contract.py`
- `crm_mcp_server/crm_mcp_server/server.py`
- `crm_mcp_server/crm_mcp_server/diagnostics.py`
- `crm_mcp_server/tests/test_smoke_check.py`
- `crm_mcp_server/tests/test_forbidden_tools.py`
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Scope confirmations:

- `crm_smoke_check` is exposed as a read-only tool name.
- Default disabled config returns `runtime_enabled=false` and sanitized `config_missing` diagnostics.
- Mocked empty result returns `INCONCLUSIVE` / `empty_result` with counts only.
- Mocked one-record result returns sanitized counts only.
- Mocked GraphQL error returns sanitized `graphql_error` diagnostics with error count only.
- Mocked unauthorized response returns sanitized `unauthorized_or_forbidden` diagnostics.
- `mutation_used` remains `false`; `mutations_allowed` remains `false`.
- Outputs are restricted to `status`, `read_only`, `mutations_allowed`, `runtime_enabled`, `allowed_operations`, `operation_name`, `mutation_used`, `http_status_category`, `graphql_errors_count`, `data_count`, `normalized_count`, `reason`, and `errors`.
- Tests and safety assertions verify endpoint value, token, Authorization/Bearer text, raw GraphQL request/response markers, customer/project names, amount, contact, phone, email, and free-text CRM note markers do not appear in output.
- No real HTTP transport was implemented.
- No real CRM endpoint was accessed.
- `.env.nanobot` was not read.
- No token, secret, endpoint auth header, or raw GraphQL payload was added or output.
- No Mutation behavior, Nanobot config wiring, DingTalk integration, or Nanobot runtime core change was added.

Remaining gaps:

- 15D uses mocked transport only; no real CRM smoke is approved or executed.
- 15E remains the next task for `crm_list_projects` with mocked GraphQL responses.

## 2026-05-07 - Task 15E: Implement `crm_list_projects` with mocked GraphQL responses

TDD cycle:

- Failing test command: `uv run --extra dev pytest crm_mcp_server/tests/test_list_projects.py`
- Failing test result: `13 failed`; `crm_list_projects` was not in `list_v1_tools()` and `crm_mcp_server.projects` did not exist, confirming the project listing tool path was absent.
- Minimal implementation: added `crm_list_projects` to the read-only MCP tool contract, added `crm_mcp_server/crm_mcp_server/projects.py` with mocked `listProject` operation construction, input validation before transport, pagination with `search.skip`/`search.limit`, max record/page caps, sanitized project records, sanitized source refs, sanitized errors, and diagnostics.
- Focused passing command: `uv run --extra dev pytest crm_mcp_server/tests/test_list_projects.py`
- Focused passing result: `13 passed in 0.02s`.
- First full MCP test command: `uv run --extra dev pytest crm_mcp_server/tests`
- First full MCP test result after implementation: `1 failed, 34 passed` because the older exact tool-list assertion did not yet include `crm_list_projects`.
- Minimal regression fix: updated `crm_mcp_server/tests/test_forbidden_tools.py` to include `crm_list_projects` in `V1_READ_ONLY_TOOL_NAMES`.

Final verification:

- Requested test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Requested test result: `35 passed in 0.03s`.
- Requested lint command: `uv run --extra dev ruff check crm_mcp_server`
- Requested lint result: `All checks passed!`.
- Safety assertion command: `PYTHONPATH=crm_mcp_server uv run --extra dev python - <<'PY' ... PY`
- Safety assertion result: `15E safety assertions passed`.

Files changed:

- `crm_mcp_server/crm_mcp_server/contract.py`
- `crm_mcp_server/crm_mcp_server/server.py`
- `crm_mcp_server/crm_mcp_server/projects.py`
- `crm_mcp_server/tests/test_list_projects.py`
- `crm_mcp_server/tests/test_forbidden_tools.py`
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Scope confirmations:

- `crm_list_projects` is exposed as a read-only tool name.
- `crm_list_projects` uses fixed allow-listed GraphQL operation `listProject` through `build_read_operation`.
- Input validation happens before `transport.execute(...)` for missing `window.start`, missing `window.end`, `window.start > window.end`, missing `scope.scope_id`, `max_records <= 0`, and `max_records` above server cap.
- Pagination uses `search.skip` and `search.limit`.
- Default page size is `50`; `MAX_RECORDS_CAP` is `200`; `MAX_PAGES` is `5`.
- Mocked `listProject` responses normalize only allowed record fields: `id`, `stage`, `owner.id`, `owner.name`, `created_at`, `updated_at`, and `source_ref_ids`.
- Source refs include `id`, `system=crm-graphql`, `query=listProject`, `entity_type=Project`, `source_id`, and allowed `fields`.
- Diagnostics include `read_only=true`, `mutation_used=false`, `operation_name=listProject`, `records_returned`, `pages_read`, `max_records`, `status`, and `reason`.
- GraphQL errors return sanitized `graphql_error` category without original message or extensions.
- Empty result returns empty `records`, empty `source_refs`, no errors, and sanitized `empty_result` diagnostics.
- Tests and safety assertions verify raw GraphQL request/response markers, endpoint, token, Authorization, Bearer, cookie, synthetic project/customer names, amount, phone, email, contact, address, and free-text CRM note markers do not appear in output.
- No real HTTP transport was implemented.
- No real CRM endpoint was accessed.
- No `.env*` file, including `.env.nanobot`, was read.
- No token, secret, endpoint auth header, cookie, raw GraphQL payload, project/customer data, amount, or contact detail was output.
- No Mutation behavior, raw GraphQL passthrough, Nanobot MCP config wiring, DingTalk integration, or Nanobot runtime core change was added.

Remaining gaps:

- 15E uses mocked transport only; no real CRM smoke is approved or executed.
- 15F remains the next task for redaction and diagnostics hardening tests.

## 2026-05-07 - Task 15F: Implement redaction and diagnostics tests

Baseline confirmation:

- Baseline test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Baseline test result: `35 passed in 0.03s`, confirming 15E test suite was green before 15F changes.
- Baseline lint command: `uv run --extra dev ruff check crm_mcp_server`
- Baseline lint result: `All checks passed!`.

TDD cycle:

- Failing test command: `uv run --extra dev pytest crm_mcp_server/tests/test_redaction.py -v`
- Failing test result: `5 failed, 3 passed`; `crm_mcp_server.redaction` did not exist, existing tool errors returned only `category`, and `crm_list_projects` diagnostics lacked the tightened allow-list fields.
- Minimal implementation: added `crm_mcp_server/crm_mcp_server/redaction.py` with `sanitize_error` and `sanitize_errors`, wired `crm_smoke_check` and `crm_list_projects` to emit uniform `ToolError` objects with `category`, fixed safe `message`, and `retryable`, and tightened project diagnostics with `mutations_allowed`, `graphql_errors_count`, and `pagination_limit_reached`.
- Focused passing command: `uv run --extra dev pytest crm_mcp_server/tests/test_redaction.py -v`
- Focused passing result: `8 passed in 0.02s`.

Systematic debugging note:

- After wiring uniform errors, full MCP tests initially failed because older 15D/15E tests still asserted category-only errors and the previous shorter diagnostics shape.
- Root cause: 15F intentionally changed the public safe error/diagnostics contract while the legacy tests still encoded the older contract.
- Test updates: updated `crm_mcp_server/tests/test_smoke_check.py` and `crm_mcp_server/tests/test_list_projects.py` to assert the strengthened safe error shape and diagnostics allow-lists.
- Additional root causes exposed by updated tests: `crm_list_projects` hard-coded `graphql_errors_count=0` and accepted empty source ids.
- Minimal fixes: set `graphql_errors_count` from GraphQL error count and return sanitized `missing_required_fields` when a mocked record lacks a source id.
- Redaction-related passing command after fixes: `uv run --extra dev pytest crm_mcp_server/tests/test_list_projects.py crm_mcp_server/tests/test_redaction.py crm_mcp_server/tests/test_smoke_check.py`
- Redaction-related passing result: `29 passed in 0.03s`.

Final verification:

- Requested full test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Requested full test result: `44 passed in 0.03s`.
- Requested lint command: `uv run --extra dev ruff check crm_mcp_server`
- Requested lint result: `All checks passed!`.
- Requested source safety command with plain `python`: failed to start with `zsh:1: command not found: python`; no assertion ran.
- Source safety re-run command: `uv run python - <<'PY' ... PY`
- Source safety re-run result: `15F source safety assertions passed`.

Files changed:

- `crm_mcp_server/crm_mcp_server/redaction.py`
- `crm_mcp_server/crm_mcp_server/diagnostics.py`
- `crm_mcp_server/crm_mcp_server/projects.py`
- `crm_mcp_server/tests/test_redaction.py`
- `crm_mcp_server/tests/test_smoke_check.py`
- `crm_mcp_server/tests/test_list_projects.py`
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Scope confirmations:

- `sanitize_error("graphql_error", raw_message)` returns a safe fixed message and does not leak raw GraphQL error text.
- `sanitize_error("unauthorized_or_forbidden", raw_message)` returns a safe fixed message and does not leak token/Auth/Bearer/cookie text.
- Unknown error categories safely fall back to `internal_error`.
- `crm_smoke_check` output paths for disabled config, success, empty result, GraphQL error, and unauthorized remain sanitized and allow-list constrained.
- `crm_list_projects` output paths for success, empty result, GraphQL error, invalid request, pagination limit, and missing required source id remain sanitized and allow-list constrained.
- Tool errors now use uniform `category`, `message`, and `retryable` shape.
- Project diagnostics include `read_only`, `mutations_allowed`, `mutation_used`, `operation_name`, `graphql_errors_count`, `records_returned`, `pages_read`, `max_records`, `pagination_limit_reached`, `status`, and `reason` only.
- Tests cover sensitive marker exclusion for endpoint-like strings, token-like strings, Authorization/Bearer/cookie markers, raw GraphQL request/response markers, query/variables markers, synthetic project/customer names, amount-like values, contact, phone, email, address, and free-text CRM notes.
- Source safety assertion confirms runtime package files do not contain `os.environ`, `dotenv`, `.env`, `requests.`, `httpx.`, `urllib.request`, `aiohttp.`, `Authorization`, or `Bearer `.
- No real CRM endpoint was accessed.
- No `.env*` file, including `.env.nanobot`, was read.
- No token, secret, endpoint auth header, cookie, raw GraphQL payload, project/customer data, amount, contact detail, or free-text CRM note was output.
- No Mutation behavior, raw GraphQL passthrough, real HTTP transport, Nanobot MCP config wiring, DingTalk integration, or Nanobot runtime core change was added.

Remaining gaps:

- 15F hardens mocked-tool redaction and diagnostics only; no real CRM smoke is approved or executed.
- 15G remains the next task for Docker/stdio/HTTP MCP configuration docs.

## 2026-05-07 - Task 15G: Add Docker/stdio/HTTP MCP configuration docs

15F confirmation before 15G:

- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md` recorded task 15F complete.
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md` recorded the 15F redaction helper, diagnostics safety, `crm_smoke_check`, `crm_list_projects`, test, lint, and source safety results.
- 15F evidence recorded final `uv run --extra dev pytest crm_mcp_server/tests` result as `44 passed in 0.03s`.
- 15F evidence recorded final `uv run --extra dev ruff check crm_mcp_server` result as `All checks passed!`.

Documentation changes:

- Added `docs/crm/MCP_CONFIGURATION.md` with future-only stdio MCP, HTTP MCP, Docker/Compose, token-handling, enabled-tool, forbidden-tool, and manual verification guidance.
- Updated `docs/crm/README.md` to include `MCP_CONFIGURATION.md` and current 15G MCP server status.
- Updated `docs/crm/MCP_SERVER_DESIGN.md` deployment notes to reference configuration guidance and state the 15G no-runtime scope.
- Updated `docs/crm/MANUAL_TEST.md` with future MCP configuration checks, token boundaries, and docs safety assertion guidance.
- Updated `docs/crm/DOCS_INVENTORY.md` to classify `docs/crm/MCP_CONFIGURATION.md` as canonical.
- Updated `crm_mcp_server/README.md` with current mocked tool status and future-only configuration note.

Systematic debugging note:

- Initial docs safety scan found forbidden marker matches in the documentation itself because the sample assertion listed the exact forbidden strings it intended to detect.
- Root cause: self-matching documentation snippet, not leaked credentials or unsafe runtime output.
- Minimal fix: updated the sample assertions in `docs/crm/MCP_CONFIGURATION.md` and `docs/crm/MANUAL_TEST.md` to assemble the forbidden strings while preserving the same runtime checks.

Scope confirmations:

- No runtime code was changed.
- No `docker-compose.yml` or Dockerfile was changed.
- No Nanobot runtime config was changed.
- No DingTalk files were changed.
- No real CRM adapter or internal `RealCRMAdapter` path was changed.
- No real CRM endpoint was accessed.
- No `.env*` file, including `.env.nanobot`, was read.
- No token was requested from the user or written into docs, `.dek`, tests, fixtures, or git.
- Examples use placeholders such as `<CRM_GRAPHQL_ENDPOINT>` and `<CRM_GRAPHQL_TOKEN>` only.
- Docs state that token configuration must happen outside chat and outside documentation in the local runtime environment.
- Docs state 15G does not enable real CRM, 15H mock mode does not need a token, and 15I optional real smoke requires explicit user approval.
- Docs list currently allowed tools as `crm_smoke_check` and `crm_list_projects` for future mock-mode examples.
- Docs forbid raw GraphQL passthrough, Mutation, create/update/delete/assign/contact/message/export/writeback tools, and DingTalk write/send integration.

Final verification:

- Requested test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Requested test result: `44 passed in 0.04s`.
- Requested lint command: `uv run --extra dev ruff check crm_mcp_server`
- Requested lint result: `All checks passed!`.
- Requested docs safety command with plain `python`: failed to start with `zsh:1: command not found: python`; no assertion ran.
- Docs safety re-run command: `uv run python - <<'PY' ... PY`
- Docs safety re-run result: `15G docs safety assertions passed`.

Remaining gaps:

- 15G is documentation-only; it does not prove a stdio or HTTP MCP server can be started.
- 15H remains the next task for mock-mode Nanobot MCP config wiring only.

## 2026-05-07 - Task 15H: Wire Nanobot config to CRM MCP server in mock mode

15G confirmation before 15H:

- `docs/crm/MCP_CONFIGURATION.md` exists and documents stdio MCP, HTTP MCP, Docker/Compose, token-handling, allowed-tool, forbidden-tool, and verification guidance.
- 15G docs state 15H mock mode does not need a token.
- 15G docs state 15I optional real smoke is the first task that may need a token after explicit approval.
- 15G evidence recorded `uv run --extra dev pytest crm_mcp_server/tests` as `44 passed in 0.04s`.
- 15G evidence recorded `uv run --extra dev ruff check crm_mcp_server` as `All checks passed!`.
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md` and `HANDOFF.md` were updated through 15G.

Schema discovery:

- `nanobot/config/schema.py` already supports `tools.mcpServers` through `ToolsConfig.mcp_servers` with camelCase aliasing.
- `nanobot/config/schema.py` already supports stdio MCP config through `MCPServerConfig.command` and `args`.
- `nanobot/config/schema.py` already supports HTTP-family MCP config through `MCPServerConfig.url` and `type` values `sse` / `streamableHttp`, with auto-detection possible when type is omitted.
- `nanobot/config/schema.py` already supports `enabledTools` and `toolTimeout` through camelCase aliases for `enabled_tools` and `tool_timeout`.
- No schema change was needed.

TDD cycle:

- Failing test command: `uv run --extra dev pytest tests/config/test_crm_mcp_config.py`
- Failing test result: `3 failed`; all failures were `FileNotFoundError` for missing `docs/crm/examples/nanobot-crm-mcp.mock.yaml`, proving the test expected the new mock config example.
- Minimal implementation: added `docs/crm/examples/nanobot-crm-mcp.mock.yaml` with a stdio CRM MCP server config using `uv run --project crm_mcp_server python -m crm_mcp_server`, enabling only `crm_smoke_check` and `crm_list_projects`, with `toolTimeout: 30` and no env or headers.
- Focused passing command: `uv run --extra dev pytest tests/config/test_crm_mcp_config.py`
- Focused passing result: `3 passed in 0.19s`.

Documentation changes:

- Updated `docs/crm/MCP_CONFIGURATION.md` to state 15H verifies the mock-mode example through Nanobot's real `Config` schema only, does not start real CRM access, and keeps tokens deferred to 15I.
- Updated `docs/crm/MCP_CONFIGURATION.md` to point to `docs/crm/examples/nanobot-crm-mcp.mock.yaml` and to use `streamableHttp` with `http://localhost:8765/mcp` as the HTTP mock/local placeholder example.
- Updated `docs/crm/MANUAL_TEST.md` with 15H mock config verification commands and a reminder not to run a real MCP server or set CRM credentials.
- Updated `docs/crm/README.md` to list the 15H mock config example and current mock-mode status.

Scope confirmations:

- No `nanobot/config/schema.py` change was made because the existing schema supports the needed MCP config fields.
- No real CRM endpoint was accessed.
- No `.env*` file, including `.env.nanobot`, was read.
- No token was requested from the user or written into docs, config examples, tests, fixtures, or `.dek`.
- The mock example does not contain `CRM_GRAPHQL_TOKEN`, `NANOBOT_API_KEY`, `Authorization`, `Bearer`, `.env`, `api.in.chaitin.net`, or `crm/query`.
- The mock example enables only `crm_smoke_check` and `crm_list_projects`.
- The mock example does not enable write-like tool names containing create/update/delete/remove/assign/claim/transfer/review/audit/sync/send/contact/message/task/export/writeback.
- No real CRM HTTP transport, GraphQL endpoint wiring, DingTalk integration, Mutation behavior, raw GraphQL passthrough, Dockerfile, `docker-compose.yml`, or `entrypoint.sh` change was made.

Final verification:

- Requested focused config test command: `uv run --extra dev pytest tests/config/test_crm_mcp_config.py`
- Initial final focused config test result before lint fix: `3 passed in 0.20s`.
- Requested CRM MCP test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Initial final CRM MCP test result before lint/docs fixes: `44 passed in 0.03s`.
- Requested lint command: `uv run --extra dev ruff check tests/config/test_crm_mcp_config.py crm_mcp_server`
- Initial lint result: failed with one import-order issue in `tests/config/test_crm_mcp_config.py`.
- Lint fix command: `uv run --extra dev ruff check --fix tests/config/test_crm_mcp_config.py`
- Lint fix result: `Found 1 error (1 fixed, 0 remaining).`
- Requested docs safety command with plain `python`: failed to start with `zsh:1: command not found: python`; no assertion ran.
- Docs safety re-run via `uv run python - <<'PY' ... PY` initially failed because `docs/crm/MCP_CONFIGURATION.md` and `docs/crm/MANUAL_TEST.md` still contained `CRM_GRAPHQL_TOKEN=` assignment examples from 15G.
- Minimal docs fix: replaced the future 15I token assignment snippets with non-assignment placeholders for `CRM_GRAPHQL_ENDPOINT` and `CRM_GRAPHQL_TOKEN`.
- Docs safety re-run then failed because `docs/crm/MANUAL_TEST.md` and `docs/crm/README.md` still contained the exact local env-file marker forbidden by the 15H assertion.
- Minimal docs fix: changed those 15H-scoped docs to refer to local `.env*` files generically instead of the exact marker.
- Final focused config test command: `uv run --extra dev pytest tests/config/test_crm_mcp_config.py`
- Final focused config test result: `3 passed in 0.21s`.
- Final CRM MCP test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Final CRM MCP test result: `44 passed in 0.03s`.
- Final lint command: `uv run --extra dev ruff check tests/config/test_crm_mcp_config.py crm_mcp_server`
- Final lint result: `All checks passed!`.
- Final docs safety assertion command: `uv run python - <<'PY' ... PY`
- Final docs safety assertion result: `15H config docs safety assertions passed`.

Remaining gaps:

- 15H verifies Nanobot schema parsing for mock-mode config only; it does not start the CRM MCP Server process.
- 15I remains optional and must not run without explicit user approval and runtime configuration outside chat.

## 2026-05-08 - Task 15I: Optional real MCP smoke with user-provided env outside chat

15H confirmation before 15I:

- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md` recorded task 15H complete.
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md` recorded the 15H mock config example, real Nanobot `Config` schema parse test, read-only enabled tools, CRM MCP tests, ruff, and docs safety assertion.
- 15H verification recorded `uv run --extra dev pytest tests/config/test_crm_mcp_config.py` as `3 passed in 0.21s`.
- 15H verification recorded `uv run --extra dev pytest crm_mcp_server/tests` as `44 passed in 0.03s`.
- 15H verification recorded `uv run --extra dev ruff check tests/config/test_crm_mcp_config.py crm_mcp_server` as `All checks passed!`.

Safety handling:

- A credential value was pasted into chat by the user. It was not used, printed, stored, or copied into files.
- 15I implementation uses only runtime environment variables visible to the process. It does not use credential values from chat.
- No `.env*` file was read.
- No token, endpoint value, raw GraphQL request, raw GraphQL response, variables, customer data, project data, contact data, amount, address, or free-text note was written to docs, tests, fixtures, `.dek`, stdout summaries, or final evidence.

TDD cycle:

- Failing test command: `uv run --extra dev pytest crm_mcp_server/tests/test_real_smoke.py`
- Failing test result: `7 failed`; `crm_mcp_server.real_smoke` did not exist and the source file was missing.
- Minimal implementation: added `crm_mcp_server/crm_mcp_server/real_smoke.py` with `RealSmokeConfig`, `RealGraphQLSmokeTransport`, `load_real_smoke_config_from_env()`, `run_real_crm_smoke()`, and module `main()` that prints sanitized JSON diagnostics only.
- Focused passing command: `uv run --extra dev pytest crm_mcp_server/tests/test_real_smoke.py`
- Focused passing result after implementation: `7 passed in 0.02s`.

Systematic debugging notes:

- Full CRM MCP tests initially failed because the 15F source safety test forbade all env/network access in every runtime package file. 15I explicitly adds the approved optional real-smoke env and stdlib HTTP path in `real_smoke.py` only.
- Minimal fix: exempted only `real_smoke.py` from the older blanket no-env/no-network source assertion and kept focused `test_real_smoke.py` source safety coverage for that file.
- Ruff initially failed due to an unused `sys` import in `real_smoke.py` and import ordering in `test_real_smoke.py`.
- Minimal fix: removed unused import and ran `uv run --extra dev ruff check --fix crm_mcp_server`.
- Requested plain `python - <<'PY' ... PY` source safety command did not run because `python` is not on PATH; the same assertion passed via `uv run python`.
- Requested real smoke command from repository root failed before module execution with `No module named crm_mcp_server.real_smoke` because the independent package is not installed on the root project module path.
- Minimal execution adjustment: used the independent package form `uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke` without wiring Nanobot runtime.

Pre-real-smoke verification:

- Focused unit test command: `uv run --extra dev pytest crm_mcp_server/tests/test_real_smoke.py`
- Focused unit test result before final module-main test addition: `7 passed in 0.02s`.
- Full CRM MCP test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Full CRM MCP test result after source assertion fix: `51 passed in 0.06s`.
- Lint command: `uv run --extra dev ruff check crm_mcp_server`
- Lint result after fix: `All checks passed!`.
- Source safety command: `uv run python - <<'PY' ... PY`
- Source safety result: `15I source safety assertions passed`.

Real smoke execution:

- Requested command: `uv run --extra dev python -m crm_mcp_server.real_smoke`
- Requested command result: failed before module execution with `No module named crm_mcp_server.real_smoke`; no CRM request was made by that command.
- Package-local command: `uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke`
- Package-local command sanitized result: status `INCONCLUSIVE`, reason `config_missing`, `runtime_enabled=false`, `http_status_category=not_attempted`, `graphql_errors_count=0`, `data_count=0`, `normalized_count=0`, `mutation_used=false`, `mutations_allowed=false`, error category `config_missing`.

Scope confirmations:

- `real_smoke.py` uses allow-listed `listProject` via `crm_smoke_check` / `build_read_operation` with variables `search.skip=0` and `search.limit=1`.
- No Mutation behavior was implemented.
- No raw GraphQL passthrough was exposed.
- No writeback/create/update/delete/contact/message/export tools were added.
- No DingTalk file or Nanobot production runtime wiring was changed.
- No real CRM data was saved to fixtures, snapshots, docs, or `.dek`.

Final verification:

- Focused unit test command: `uv run --extra dev pytest crm_mcp_server/tests/test_real_smoke.py`
- Focused unit test result: `8 passed in 0.02s`.
- Full CRM MCP test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Full CRM MCP test result: `52 passed in 0.04s`.
- Lint command: `uv run --extra dev ruff check crm_mcp_server`
- Lint result: `All checks passed!`.
- Source safety command: `uv run python - <<'PY' ... PY`
- Source safety result: `15I source safety assertions passed`.
- Final package-local smoke command: `uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke`
- Final package-local smoke sanitized result: status `INCONCLUSIVE`, reason `config_missing`, `runtime_enabled=false`, `http_status_category=not_attempted`, `graphql_errors_count=0`, `data_count=0`, `normalized_count=0`, `mutation_used=false`, `mutations_allowed=false`, error category `config_missing`.

Remaining gaps:

- A real CRM request was not made because this OpenCode/package-local runtime did not receive non-empty CRM runtime configuration outside chat.
- To get a real smoke `OK` or auth/GraphQL error category, configure runtime env outside chat so it is visible to `uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke`, then rerun only the sanitized smoke command.

### 2026-05-08

Claim: The current OpenCode process environment has both `CRM_GRAPHQL_ENDPOINT` and `CRM_GRAPHQL_TOKEN` configured with non-empty values.

Verdict: NOT VERIFIED

Commands:

- `if [ -n "${CRM_GRAPHQL_ENDPOINT+x}" ] && [ -n "$CRM_GRAPHQL_ENDPOINT" ]; then endpoint_status=configured; else endpoint_status=missing; fi; if [ -n "${CRM_GRAPHQL_TOKEN+x}" ] && [ -n "$CRM_GRAPHQL_TOKEN" ]; then token_status=configured; else token_status=missing; fi; printf 'endpoint_status=%s\ntoken_status=%s\n' "$endpoint_status" "$token_status"` — completed without printing values.

Evidence:

- `endpoint_status`: `missing`
- `token_status`: `missing`

Reasoning:

The check only tested presence and non-empty status in the current OpenCode process environment. It did not print endpoint or token values and did not read `.env*` files.

Gaps:

- This does not prove the user's interactive shell, service manager, or other terminal sessions lack these variables; it only proves they are not visible to this OpenCode process.

## 2026-05-08 - Task 15J: Cleanup review / inventory proposal only

15I status confirmation:

- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md` records 15I as implemented with package-local smoke sanitized status `INCONCLUSIVE`, reason `config_missing`, `runtime_enabled=false`, `http_status_category=not_attempted`, `graphql_errors_count=0`, `data_count=0`, `normalized_count=0`, `mutation_used=false`, and no real CRM request made.
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md` records the same 15I package-local smoke sanitized result and states a real CRM request was not made because runtime configuration was not visible to the process.

Inventory/review commands and reads:

- Read `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md` and `EVIDENCE.md` to confirm 15I sanitized status.
- Read requested inventory files: `nanobot/crm/graphql_client.py`, `nanobot/crm/real_adapter.py`, `tests/crm/test_graphql_client.py`, `tests/crm/test_real_adapter_contract.py`, `tests/crm/test_real_adapter_redaction.py`, `tests/crm/test_adapters.py`, `docs/crm-graphql-contract.md`, `docs/crm/GRAPHQL_CONTRACT.md`, `docs/crm/MIGRATION_NOTES.md`, `docs/crm/DOCS_INVENTORY.md`, `.dek/changes/crm-opportunity-intelligence/TASKS.md`, `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md`, and `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`.
- Grep search terms used for inventory: `RealCRMAdapter`, `graphql_client`, `CRMGraphQLClient`, `direct GraphQL`, `in-process`, `docs/crm-graphql-contract.md`, `14E`, `14F`, `MCP-first`, and `superseded`.
- Additional related direct-route artifact found: `nanobot/crm/real_smoke_diagnostics.py` and `tests/crm/test_real_smoke_diagnostics.py` still reference the superseded direct adapter route.

Docs changed:

- Added `docs/crm/REAL_ADAPTER_CLEANUP_REVIEW.md` with keep / superseded-reference / archive-candidate / delete-candidate / needs-user-decision classifications and cleanup options A, B, and C.
- Updated `docs/crm/DOCS_INVENTORY.md` to classify `REAL_ADAPTER_CLEANUP_REVIEW.md`, clarify `docs/crm-graphql-contract.md` as superseded-reference / archive-candidate, and classify direct adapter code/tests as superseded-reference rather than production route.
- Updated `docs/crm/MIGRATION_NOTES.md` to link the cleanup review and state cleanup requires explicit user approval.

Scope confirmations:

- No real CRM access.
- No real CRM smoke rerun.
- No `.env*` file, including `.env.nanobot`, was read.
- No token, auth header, Bearer value, raw GraphQL request/response, GraphQL variables, real customer/project/contact data, amount, address, or CRM free-text content was output or recorded.
- No files were deleted.
- No files were moved.
- No files were renamed.
- No runtime business code was changed.
- No tests were modified to skip the old route.
- No DingTalk cleanup or writeback/Mutation work was done.

Recommended cleanup option:

- Option B: archive or strongly mark superseded docs first, while keeping direct adapter code/tests as reference until the MCP path proves stable.

Verification:

- Test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Test result: `52 passed in 0.04s`.
- Lint command: `uv run --extra dev ruff check crm_mcp_server`
- Lint result: `All checks passed!`.
- Requested cleanup review assertion with plain `python`: failed to start with `zsh:1: command not found: python`; no assertion ran.
- Cleanup review assertion re-run command: `uv run python - <<'PY' ... PY`
- Cleanup review assertion re-run result: `15J cleanup review assertions passed`.

Remaining pending decision:

- Wait for explicit user approval of cleanup Option A, Option B, or Option C before any actual archive, delete, move, rename, runtime-code edit, or test edit.

## 2026-05-08 - Task 15J Option B: Archive superseded docs in place

Approval:

- User requested 15J review and selected Option B.

Changes:

- Updated `docs/crm-graphql-contract.md` with an archived-in-place superseded-reference header pointing to `docs/crm/GRAPHQL_CONTRACT.md` as canonical.
- Updated `docs/crm/REAL_ADAPTER_CLEANUP_REVIEW.md` to record Option B as selected and applied.
- Updated `docs/crm/DOCS_INVENTORY.md` to classify `docs/crm-graphql-contract.md` as archived-in-place / superseded-reference.
- Updated `docs/crm/MIGRATION_NOTES.md` to record Option B and clarify direct adapter code/tests remain reference material.
- Updated `PROGRESS.md` and `HANDOFF.md` for Option B completion.

Scope confirmations:

- No real CRM access.
- No real CRM smoke rerun.
- No `.env*` file, including `.env.nanobot`, was read.
- No token, auth header, Bearer value, raw GraphQL request/response, GraphQL variables, real customer/project/contact data, amount, address, or CRM free-text content was output or recorded.
- No files were deleted.
- No files were moved.
- No files were renamed.
- No runtime business code was changed.
- No direct adapter code or direct-route tests were edited.
- No tests were modified to skip the old route.
- No DingTalk cleanup or writeback/Mutation work was done.

Verification results are recorded after the final verification commands for this task.

Verification:

- Test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Test result: `52 passed in 0.04s`.
- Lint command: `uv run --extra dev ruff check crm_mcp_server`
- Lint result: `All checks passed!`.
- Requested Option B assertion with plain `python`: failed to start with `zsh:1: command not found: python`; no assertion ran.
- Option B assertion re-run command: `uv run python - <<'PY' ... PY`
- Option B assertion re-run result: `15J Option B cleanup assertions passed`.
- Final Option B status assertion command: `uv run python - <<'PY' ... PY`
- Final Option B status assertion result: `15J Option B final assertions passed`.

Remaining pending decision:

- Option B is complete. Deeper cleanup, including moving/deleting direct adapter code/tests or handling `nanobot/crm/real_smoke_diagnostics.py`, still requires future explicit user approval.

## 2026-05-08 - Task 15K: Execute approved cleanup Option B

Approval:

- User requested Task 15K to execute approved cleanup Option B: archive/mark superseded direct GraphQL docs, keep `nanobot/crm/graphql_client.py` and `nanobot/crm/real_adapter.py` as superseded references, keep related tests as reference/safety material, and do not delete code or tests.

Files changed:

- `docs/crm-graphql-contract.md`: strengthened the top superseded-reference header with the requested blockquote wording and canonical `docs/crm/GRAPHQL_CONTRACT.md` pointer.
- `docs/crm/DOCS_INVENTORY.md`: updated classifications for canonical `docs/crm/GRAPHQL_CONTRACT.md`, superseded root GraphQL doc, direct adapter code, and related tests.
- `docs/crm/MIGRATION_NOTES.md`: recorded production real CRM access route as CRM MCP Server, direct in-process Nanobot GraphQL route as superseded, Option B as selected/executed, code/tests retained, and `No files deleted`.
- `docs/crm/README.md`: clarified canonical docs live under `docs/crm/`, MCP Server is the current real CRM access direction, root GraphQL doc is superseded/reference only, DingTalk remains deferred, and writeback remains out of scope.
- `.dek/changes/crm-opportunity-intelligence/TASKS.md`: added 15K task record and reinforced that 14E/14F/direct-route continuation is not production work without explicit user approval.
- `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md`: clarified Nanobot does not directly own real CRM GraphQL access for production and direct adapter code/tests are retained reference only.
- `nanobot/crm/graphql_client.py`: updated module docstring only to mark it as superseded reference material.
- `nanobot/crm/real_adapter.py`: updated module docstring only to mark it as superseded reference material.

Scope confirmations:

- No file was deleted.
- No file was moved.
- No file was renamed.
- No tests were deleted.
- No runtime behavior was changed; Python edits were module docstrings only.
- No CRM MCP Server implementation or tool behavior was changed.
- No real CRM access.
- No real CRM smoke run.
- No `.env*` file, including `.env.nanobot`, was read.
- No token was requested.
- No token, auth header, Bearer value, raw GraphQL request/response, GraphQL variables, real customer/project/contact data, amount, address, or CRM free-text content was output or recorded.
- No DingTalk connection or cleanup.
- No writeback or Mutation work.

Verification:

- Test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Test result: `52 passed in 0.04s`.
- Focused direct-route reference test command: `uv run --extra dev pytest tests/crm/test_graphql_client.py tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_redaction.py`
- Focused direct-route reference test result: `20 passed in 0.24s`.
- Lint command: `uv run --extra dev ruff check crm_mcp_server nanobot/crm/graphql_client.py nanobot/crm/real_adapter.py`
- Lint result: `All checks passed!`.
- Requested safety assertion command with plain `python`: failed to start with `zsh:1: command not found: python`; no assertion ran.
- Safety assertion re-run command: `uv run python - <<'PY' ... PY`
- Safety assertion re-run result: `15K cleanup option B assertions passed`.

Remaining pending decision:

- 15K Option B cleanup is complete. Next choice is to finish branch / commit / PR, or continue building the next MCP data tool. Deeper cleanup such as moving/deleting direct adapter code/tests or handling `nanobot/crm/real_smoke_diagnostics.py` still requires future explicit user approval.

## 2026-05-08 - Task 16A: Implement `crm_list_business_chances` with mocked GraphQL responses

Scope:

- Implemented CRM MCP Server read-only tool `crm_list_business_chances` using mocked transport only.
- Fixed GraphQL operation name is `list_business_chance`.
- No real CRM access, real smoke, `.env*` reads, token handling, DingTalk work, Mutation, writeback, or raw GraphQL passthrough was performed.

TDD cycle:

- Failing test command: `uv run --extra dev pytest crm_mcp_server/tests/test_list_business_chances.py`
- Failing test result: `14 failed`; `crm_list_business_chances` was not in `list_v1_tools()` and `crm_mcp_server.business_chances` did not exist.
- Minimal implementation: added `crm_mcp_server/crm_mcp_server/business_chances.py`, added `crm_list_business_chances` to the read-only tool contract and server metadata, and implemented validation-before-transport, fixed `list_business_chance` operation construction, pagination using `search.skip`/`search.limit`, caps, sanitized record normalization, source refs, diagnostics, and sanitized errors.
- Focused passing command: `uv run --extra dev pytest crm_mcp_server/tests/test_list_business_chances.py`
- Focused passing result: `14 passed in 0.02s`.

Systematic debugging note:

- Full MCP test command after focused pass initially returned `1 failed, 65 passed`.
- Root cause: `crm_mcp_server/tests/test_forbidden_tools.py` intentionally has an exact read-only tool-list assertion and still encoded the pre-16A list.
- Minimal fix: added `crm_list_business_chances` to that exact expected tuple while preserving write-like tool-name assertions.
- Full MCP test re-run result after fix: `66 passed in 0.05s`.

Files changed:

- `crm_mcp_server/crm_mcp_server/business_chances.py`
- `crm_mcp_server/crm_mcp_server/contract.py`
- `crm_mcp_server/crm_mcp_server/server.py`
- `crm_mcp_server/tests/test_list_business_chances.py`
- `crm_mcp_server/tests/test_forbidden_tools.py`
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Scope confirmations:

- `crm_list_business_chances` is exposed as a read-only tool name.
- `crm_list_business_chances` uses fixed allow-listed GraphQL operation `list_business_chance` through `build_read_operation`.
- Input validation happens before `transport.execute(...)` for missing `window.start`, missing `window.end`, `window.start > window.end`, missing `scope.scope_id`, `max_records <= 0`, and `max_records` above server cap.
- Pagination uses `search.skip` and `search.limit`.
- Default page size is `50`; `MAX_RECORDS_CAP` is `200`; `MAX_PAGES` is `5`.
- Mocked `list_business_chance` responses normalize only allowed record fields: `id`, `project_id`, `status`, `apply_status`, `owner.id`, `owner.name`, `due_at`, `created_at`, `updated_at`, and `source_ref_ids`.
- Source refs include `id`, `system=crm-graphql`, `query=list_business_chance`, `entity_type=BusinessChance`, `source_id`, and allowed `fields`.
- Diagnostics include `read_only=true`, `mutations_allowed=false`, `mutation_used=false`, `operation_name=list_business_chance`, `graphql_errors_count`, `records_returned`, `pages_read`, `max_records`, `pagination_limit_reached`, `status`, and `reason` only.
- GraphQL errors return sanitized `graphql_error` category without original message or extensions.
- Empty result returns empty `records`, empty `source_refs`, no errors, and sanitized `empty_result` diagnostics.
- Tests verify raw GraphQL request/response markers, endpoint, token, Authorization, Bearer, cookie, synthetic project/customer names, amount, phone, email, contact, address, and free-text CRM note markers do not appear in output.
- No real HTTP transport was implemented.
- No real CRM endpoint was accessed.
- No `.env*` file, including `.env.nanobot`, was read.
- No token, secret, endpoint auth header, cookie, raw GraphQL payload, project/customer names, amount, or contact detail was output.
- No Mutation behavior, raw GraphQL passthrough, Nanobot MCP config wiring, DingTalk integration, or Nanobot runtime core change was added.

Final verification:

- Requested full test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Requested full test result: `66 passed in 0.05s`.
- Requested lint command: `uv run --extra dev ruff check crm_mcp_server`
- Requested lint result: `All checks passed!`.

## 2026-05-08 - Task 16B: Implement `crm_generate_daily_report_facts` with mocked read-tool outputs

Scope:

- Implemented CRM MCP Server report facts tool `crm_generate_daily_report_facts` using mocked dependency readers only.
- The tool composes sanitized report facts from `crm_list_projects`-style and `crm_list_business_chances`-style outputs.
- No real CRM access, real smoke, `.env*` reads, token handling, DingTalk work, Mutation, writeback, or raw GraphQL passthrough was performed.

Branch setup:

- The session started on branch `16A`, while the requested precondition said 16A was already merged into `main` and current work should start from latest `main`.
- Local `main` did not contain commit `3e8e4c5c feat(crm-mcp): add business chance read tool`; only branch `16A` did.
- Local `main` was fast-forwarded to `16A`, then branch `16B` was created from updated `main`.

TDD cycle:

- Failing test command: `uv run --extra dev pytest crm_mcp_server/tests/test_daily_report_facts.py`
- Failing test result: `16 failed, 1 passed`; `crm_mcp_server.daily_report` did not exist. The existing static metadata already exposed `crm_generate_daily_report_facts` as read-only.
- Minimal implementation: added `crm_mcp_server/crm_mcp_server/daily_report.py` with validation-before-reader-calls, sanitized request echoing, dependency reader injection, project/business chance count metrics, business chance status/apply-status distributions, due-today and overdue counts, source-ref merge/deduplication, unavailable metric handling for dependency errors, and allow-listed diagnostics.
- Focused passing command: `uv run --extra dev pytest crm_mcp_server/tests/test_daily_report_facts.py`
- Focused passing result: `17 passed in 0.02s`.

Files changed:

- `crm_mcp_server/crm_mcp_server/daily_report.py`
- `crm_mcp_server/tests/test_daily_report_facts.py`
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Scope confirmations:

- `crm_generate_daily_report_facts` is exposed as a read-only tool name in the existing static contract and server metadata.
- Validation happens before dependency reader calls for missing `window.start`, missing `window.end`, non-daily windows where `start != end`, missing `scope.scope_id`, invalid `max_records`, and `max_records` above the server cap.
- Implemented metrics: `project_count`, `business_chance_count`, `business_chance_status_distribution`, `business_chance_apply_status_distribution`, `business_chance_due_today_count`, and `business_chance_overdue_count`.
- Dependency errors produce sanitized unavailable metric records with `reason=dependency_error`; dependent values are not inferred.
- `include_source_refs=false` returns empty `source_refs` and empty metric `source_ref_ids`.
- `include_unavailable_metrics=false` omits unavailable metric records.
- Source refs are merged from project and business chance dependency outputs and deduplicated by `id`.
- Diagnostics include only `status`, `reason`, `read_only`, `mutations_allowed`, `mutation_used`, `dependency_tools`, `project_records_count`, `business_chance_records_count`, `metrics_count`, and `unavailable_metrics_count`.
- Tests verify raw GraphQL request/response markers, endpoint, token, Authorization, Bearer, synthetic project/customer names, amount, phone, email, contact, address, and free-text CRM note markers do not appear in report output.
- No real HTTP transport was implemented.
- No real CRM endpoint was accessed.
- No `.env*` file, including `.env.nanobot`, was read.
- No token, secret, endpoint auth header, cookie, raw GraphQL payload, project/customer names, amount, contact detail, or free-text CRM note was output.
- No Mutation behavior, raw GraphQL passthrough, Nanobot MCP config wiring, DingTalk integration, old `RealCRMAdapter` route change, or Nanobot runtime core change was added.

Final verification:

- Focused test command: `uv run --extra dev pytest crm_mcp_server/tests/test_daily_report_facts.py`
- Focused test result: `17 passed in 0.02s`.
- Full MCP test command: `uv run --extra dev pytest crm_mcp_server/tests`
- Full MCP test result: `83 passed in 0.06s`.
- Lint command: `uv run --extra dev ruff check crm_mcp_server`
- Lint result: `All checks passed!`.
- Requested plain safety assertion command: `python - <<'PY' ... PY`
- Requested plain safety assertion result: did not start because `python` is not on PATH in this shell (`zsh:1: command not found: python`).
- Equivalent safety assertion command: `uv run python - <<'PY' ... PY`
- Equivalent safety assertion result: `16B source safety assertions passed`.
