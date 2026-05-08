# CRM Opportunity Intelligence Implementation Tasks

Change id: `crm-opportunity-intelligence`

Source architecture: `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md`

Execution rules:

- Each task does one thing.
- Prefer TDD: write or update the failing test/check before implementation.
- Use only synthetic or mocked CRM data in tests and fixtures.
- Do not read, request, log, or commit real CRM data, customer data, tokens, or secrets.
- Keep `.dek` as development governance only; production runtime must not depend on `.dek`.
- MCP-first update: implement in this order for future work: keep existing Nanobot mock/report/metrics/evidence, design and implement a separate CRM MCP Server, wire Nanobot to MCP in mock mode, then optionally run real MCP smoke only with explicit user approval and runtime environment outside chat.
- Do not continue expanding the in-process `RealCRMAdapter` direct GraphQL path for production real CRM access.
- DingTalk CRM delivery is deferred.
- CRM writeback is out of scope and requires a separate change proposal.

## MCP-first status update

Canonical docs:

- `docs/crm/README.md`
- `docs/crm/GRAPHQL_CONTRACT.md`
- `docs/crm/MCP_SERVER_DESIGN.md`
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `docs/crm/MANUAL_TEST.md`
- `docs/crm/MIGRATION_NOTES.md`
- `docs/crm/DOCS_INVENTORY.md`

Retained Nanobot internals:

- `nanobot/crm/models.py`
- `nanobot/crm/mock_adapter.py`
- `nanobot/crm/metrics.py`
- `nanobot/crm/evidence.py`
- `nanobot/crm/reports.py`
- mock CLI path

Superseded path:

- The direct in-process GraphQL client and `RealCRMAdapter` route is superseded for production real CRM access.
- Existing completed direct-adapter code and tests remain historical/reference material until explicit user-approved cleanup.
- `nanobot/crm/graphql_client.py`, `nanobot/crm/real_adapter.py`, and related direct-route tests are retained superseded references only, not targets for production CRM access expansion.
- Future real CRM smoke must go through CRM MCP Server `crm_smoke_check` or an equivalent approved read-only MCP tool.

## 1. Confirm Nanobot extension points

Task: document the concrete extension seams that the CRM implementation will use.

Files touched:

- `.dek/changes/crm-opportunity-intelligence/EXTENSION_POINTS.md`

Step 1: failing check

- Create a checklist in `EXTENSION_POINTS.md` with unchecked entries for CLI, tools/MCP, skills, DingTalk, message delivery, memory safety, tests, and Docker smoke.

Step 2: minimal implementation

- Fill the checklist with confirmed file paths and the chosen first-version integration approach.
- State that CRM report logic must not be placed in `nanobot/channels/dingtalk.py`.
- State that production runtime must not depend on `.dek`.

Step 3: verification

- Run `python - <<'PY'
from pathlib import Path
p = Path('.dek/changes/crm-opportunity-intelligence/EXTENSION_POINTS.md')
text = p.read_text()
required = ['nanobot/cli/commands.py', 'nanobot/agent/tools', 'nanobot/skills', 'nanobot/channels/dingtalk.py', 'nanobot/agent/tools/message.py', 'nanobot/agent/memory.py', 'Dockerfile', 'docker-compose.yml', '.dek']
missing = [item for item in required if item not in text]
assert not missing, missing
assert 'must not be placed in `nanobot/channels/dingtalk.py`' in text
assert 'production runtime must not depend on `.dek`' in text
PY`

Step 4: cleanup/checkpoint

- Do not modify runtime code in this task.

## 2. Define standard CRM data model

Task: create the normalized CRM domain model used by adapters, metrics, reports, CLI, and DingTalk.

Files touched:

- `nanobot/crm/__init__.py`
- `nanobot/crm/models.py`
- `tests/crm/test_models.py`

Step 1: failing test

- Add tests that instantiate report request, source opportunity, metric record, unavailable metric record, evidence trace, and report output models.
- Add tests proving model modules do not import CRM clients, DingTalk channel modules, CLI command modules, or provider modules.

Step 2: minimal implementation

- Add typed dataclasses or Pydantic models for the v1 normalized CRM contract.
- Include fields for stable source references, report type, report window, scope, metric name/value, missing inputs, evidence trace id, and sanitized report content.
- Avoid any real CRM-specific SDK or network dependency.

Step 3: verification

- Run `pytest tests/crm/test_models.py`
- Run `ruff check nanobot/crm tests/crm/test_models.py`

Step 4: cleanup/checkpoint

- Keep model names narrow to v1 report needs; do not add future CRM entities that no v1 metric uses.

## 3. Create mock CRM fixture

Task: add synthetic CRM fixture data for normal and edge-case report scenarios.

Files touched:

- `tests/crm/fixtures.py`
- `tests/crm/test_fixtures.py`

Step 1: failing test

- Add tests that verify fixtures are explicitly labeled synthetic.
- Add tests that fixture records cover daily, weekly, dashboard, empty-data, missing-input, and multi-sales-user scenarios.
- Add tests that fixture strings do not contain forbidden sample tokens such as `token`, `secret`, `password`, `真实`, `客户真实`, or production-looking domains.

Step 2: minimal implementation

- Create deterministic synthetic opportunities, owners, stages, timestamps, amounts, and source references using fake identifiers.
- Keep fixture content in test files only.

Step 3: verification

- Run `pytest tests/crm/test_fixtures.py`
- Run `ruff check tests/crm/fixtures.py tests/crm/test_fixtures.py`

Step 4: cleanup/checkpoint

- Confirm no `.env*` files or real CRM exports were read or copied.

## 4. Create CRMAdapter interface

Task: define the read-only `CRMAdapter` contract and adapter error categories.

Files touched:

- `nanobot/crm/adapters.py`
- `tests/crm/test_adapters.py`

Step 1: failing test

- Add tests that assert the adapter protocol exposes only read methods.
- Add tests that assert forbidden method names such as `create`, `update`, `delete`, `assign`, `message`, `contact`, and `write` are absent.
- Add tests for stable adapter error categories.

Step 2: minimal implementation

- Add a `CRMAdapter` protocol or abstract base class with read-only methods needed by v1 report requests.
- Add sanitized exceptions or result error categories for unavailable CRM, invalid configuration, invalid scope, and missing data.
- Keep the interface independent from real CRM clients.

Step 3: verification

- Run `pytest tests/crm/test_adapters.py`
- Run `ruff check nanobot/crm/adapters.py tests/crm/test_adapters.py`

Step 4: cleanup/checkpoint

- Do not implement the real CRM adapter in this task.

## 5. Implement MockCRMAdapter

Task: implement a read-only adapter backed by synthetic fixture data.

Files touched:

- `nanobot/crm/mock_adapter.py`
- `tests/crm/test_mock_adapter.py`
- `tests/crm/fixtures.py`

Step 1: failing test

- Add tests proving `MockCRMAdapter` satisfies the `CRMAdapter` contract.
- Add tests for scoped reads by date/window and sales scope.
- Add tests for empty-data and missing-input fixture modes.
- Add tests proving no write-like methods exist on the mock adapter.

Step 2: minimal implementation

- Implement `MockCRMAdapter` using synthetic fixtures.
- Return normalized model records and stable source references.
- Return deterministic results for repeated calls.

Step 3: verification

- Run `pytest tests/crm/test_mock_adapter.py tests/crm/test_adapters.py`
- Run `ruff check nanobot/crm/mock_adapter.py tests/crm/test_mock_adapter.py`

Step 4: cleanup/checkpoint

- Keep mock adapter available for CLI smoke verification without secrets.

## 6. Implement pipeline metrics

Task: implement deterministic metric computation for daily, weekly, and dashboard inputs.

Files touched:

- `nanobot/crm/metrics.py`
- `tests/crm/test_metrics_daily.py`
- `tests/crm/test_metrics_weekly.py`
- `tests/crm/test_metrics_dashboard.py`
- `tests/crm/test_metrics_missing_inputs.py`

Step 1: failing test

- Add tests for counts, amount totals, stage/status distribution, movement summary, stalled/risk labels, won/lost summaries, owner/team aggregation, and unavailable metric markers.
- Add tests proving metrics do not import or call the LLM, DingTalk, CLI, or real CRM clients.

Step 2: minimal implementation

- Implement deterministic metric functions that accept normalized CRM records and report scope/window.
- Return metric records and unavailable metric records with missing inputs.
- Keep calculations stable and explicit.

Step 3: verification

- Run `pytest tests/crm/test_metrics_daily.py tests/crm/test_metrics_weekly.py tests/crm/test_metrics_dashboard.py tests/crm/test_metrics_missing_inputs.py`
- Run `ruff check nanobot/crm/metrics.py tests/crm/test_metrics_daily.py tests/crm/test_metrics_weekly.py tests/crm/test_metrics_dashboard.py tests/crm/test_metrics_missing_inputs.py`

Step 4: cleanup/checkpoint

- Do not add report formatting or LLM narrative in this task.

## 7. Implement daily report

Task: implement daily report assembly from mock adapter data and deterministic metrics.

Files touched:

- `nanobot/crm/reports.py`
- `tests/crm/test_report_daily.py`

Step 1: failing test

- Add tests that daily report output has fixed sections: reporting date/window, scope, deterministic metrics, key changes/risks, and evidence trace placeholder or trace ids.
- Add tests that no-data output does not invent activity.
- Add tests that missing date without configured default returns validation error before adapter read.

Step 2: minimal implementation

- Add daily report generation using `CRMAdapter` and metrics layer only.
- Return deterministic structured report output without requiring LLM narrative.
- Include unavailable metric markers when inputs are missing.

Step 3: verification

- Run `pytest tests/crm/test_report_daily.py`
- Run `ruff check nanobot/crm/reports.py tests/crm/test_report_daily.py`

Step 4: cleanup/checkpoint

- Keep report generator independent from real CRM APIs and DingTalk.

## 8. Implement weekly report

Task: implement weekly report assembly from mock adapter data and deterministic metrics.

Files touched:

- `nanobot/crm/reports.py`
- `tests/crm/test_report_weekly.py`

Step 1: failing test

- Add tests that weekly report output has fixed sections: week/date range, scope, pipeline movement, stage distribution, stalled/high-risk summary, won/lost summary, and evidence trace placeholder or trace ids.
- Add tests that week-over-week or trend claims appear only when deterministic metrics provide the comparison.
- Add tests that missing week/range without configured default returns validation error before adapter read.

Step 2: minimal implementation

- Add weekly report generation using the same report generator boundary.
- Reuse deterministic metrics and unavailable marker behavior.

Step 3: verification

- Run `pytest tests/crm/test_report_weekly.py tests/crm/test_report_daily.py`
- Run `ruff check nanobot/crm/reports.py tests/crm/test_report_weekly.py`

Step 4: cleanup/checkpoint

- Do not add DingTalk-specific output in this task.

## 9. Implement dashboard summary

Task: implement cross-sales dashboard summary from mock adapter data and deterministic metrics.

Files touched:

- `nanobot/crm/reports.py`
- `tests/crm/test_report_dashboard.py`

Step 1: failing test

- Add tests that dashboard output has fixed sections: included sales scope, pipeline status, opportunity stage/status, risk/stagnation, notable movements, and evidence trace placeholder or trace ids.
- Add tests proving dashboard output does not expose ad hoc filters, interactive drill-downs, forecasts, or custom BI query behavior.

Step 2: minimal implementation

- Add dashboard summary generation using adapter plus metrics.
- Keep output static and scoped to v1 summary sections.

Step 3: verification

- Run `pytest tests/crm/test_report_dashboard.py tests/crm/test_report_daily.py tests/crm/test_report_weekly.py`
- Run `ruff check nanobot/crm/reports.py tests/crm/test_report_dashboard.py`

Step 4: cleanup/checkpoint

- Do not implement complex BI or interactive drill-downs.

## 10. Implement CLI

Task: add a deterministic CLI entry for CRM report generation with mock adapter mode.

Files touched:

- `nanobot/crm/cli.py`
- `nanobot/cli/commands.py`
- `tests/cli/test_crm_cli.py`

Step 1: failing test

- Add CLI tests for daily, weekly, and dashboard report generation using mock adapter and synthetic data.
- Add tests for deterministic exit status on success, validation error, no-data, missing metrics, and LLM fallback mode if exposed.
- Add tests that CLI output is sanitized and includes evidence trace ids or an evidence section.

Step 2: minimal implementation

- Add a focused CLI wrapper that delegates to `nanobot.crm.reports`.
- Wire the command into `nanobot/cli/commands.py` only as a thin entry point.
- Default test/dev mode to mock adapter unless explicit non-secret config chooses otherwise.

Step 3: verification

- Run `pytest tests/cli/test_crm_cli.py`
- Run `pytest tests/crm/test_report_daily.py tests/crm/test_report_weekly.py tests/crm/test_report_dashboard.py`
- Run `ruff check nanobot/crm/cli.py nanobot/cli/commands.py tests/cli/test_crm_cli.py`

Step 4: cleanup/checkpoint

- Confirm no CRM client code is embedded in `nanobot/cli/commands.py`.

## 11. Connect Nanobot tool/skill

Task: expose report generation through a Nanobot extension seam without putting CRM logic in core agent code.

Files touched:

- `nanobot/agent/tools/crm.py`
- `nanobot/agent/loop.py`
- `nanobot/skills/crm-opportunity-intelligence/SKILL.md`
- `tests/tools/test_crm_tool.py`
- `tests/agent/test_crm_tool_registration.py`

Step 1: failing test

- Add tests that the CRM tool exposes only read/report actions for daily, weekly, and dashboard outputs.
- Add tests that forbidden CRM mutation actions are absent.
- Add registration tests only if a built-in native tool is chosen.
- Add a skill content check proving instructions mention deterministic metrics, evidence traces, and no CRM writeback.

Step 2: minimal implementation

- Add a thin read-only CRM report tool that delegates to `nanobot.crm.reports` and uses mock adapter mode by default for tests.
- Register the tool in `AgentLoop` only if native built-in tool registration is required; otherwise document MCP/configured-tool usage in the skill and skip `AgentLoop` changes.
- Add a CRM skill with report usage instructions and safety boundaries, containing no real CRM data.

Step 3: verification

- Run `pytest tests/tools/test_crm_tool.py tests/agent/test_crm_tool_registration.py`
- Run `ruff check nanobot/agent/tools/crm.py nanobot/agent/loop.py tests/tools/test_crm_tool.py tests/agent/test_crm_tool_registration.py`

Step 4: cleanup/checkpoint

- If `nanobot/agent/loop.py` is not touched, remove it from this task's final touched set and keep verification focused on tool/skill files.

## 12. Implement DingTalk fixed command

Task: add a fixed DingTalk-facing CRM report command that reuses the CLI/report generator path.

Files touched:

- `nanobot/command/builtin.py`
- `nanobot/command/router.py`
- `tests/command/test_crm_dingtalk_command.py`
- `tests/channels/test_crm_dingtalk_delivery.py`

Step 1: failing test

- Add tests for fixed commands or command arguments that request daily, weekly, and dashboard reports.
- Add tests that the command maps to the same report generator used by CLI.
- Add tests that output includes trace ids or evidence section.
- Add tests that mutation controls, approval actions, customer-contact actions, automatic task creation, automatic assignment, and ad hoc BI controls are absent.

Step 2: minimal implementation

- Add the smallest fixed command surface needed for DingTalk usage.
- Delegate report creation to `nanobot.crm.reports`.
- Use existing channel/message delivery behavior; do not put CRM report logic in `nanobot/channels/dingtalk.py`.

Step 3: verification

- Run `pytest tests/command/test_crm_dingtalk_command.py tests/channels/test_crm_dingtalk_delivery.py`
- Run `pytest tests/channels/test_dingtalk_channel.py`
- Run `ruff check nanobot/command/builtin.py nanobot/command/router.py tests/command/test_crm_dingtalk_command.py tests/channels/test_crm_dingtalk_delivery.py`

Step 4: cleanup/checkpoint

- Confirm `nanobot/channels/dingtalk.py` remains untouched unless a generic DingTalk transport gap is proven.

## 13. Implement evidence trace

Task: harden evidence trace generation and validation for all report types.

Files touched:

- `nanobot/crm/evidence.py`
- `nanobot/crm/reports.py`
- `tests/crm/test_evidence.py`
- `tests/crm/test_report_daily.py`
- `tests/crm/test_report_weekly.py`
- `tests/crm/test_report_dashboard.py`

Step 1: failing test

- Add tests that every key business conclusion references an existing trace id or trace record.
- Add tests for trace fields: metric name/value, input date/window/scope, source entity type, stable source reference, source field names, and deterministic calculation id.
- Add tests that traces do not include secrets, tokens, raw CRM payload dumps, or unnecessary raw customer details.

Step 2: minimal implementation

- Implement evidence trace builder and attach traces to daily, weekly, and dashboard output.
- Add validation for key conclusion trace coverage.
- Keep traces report-local and out of `.dek` and long-term memory paths.

Step 3: verification

- Run `pytest tests/crm/test_evidence.py tests/crm/test_report_daily.py tests/crm/test_report_weekly.py tests/crm/test_report_dashboard.py`
- Run `ruff check nanobot/crm/evidence.py nanobot/crm/reports.py tests/crm/test_evidence.py`

Step 4: cleanup/checkpoint

- Re-run `pytest tests/crm` before moving to the real adapter.

## 14A. Extract GraphQL read contract

Task: extract the read-only GraphQL contract from the provided CRM schema before implementing any real adapter code.

Files touched:

- `docs/crm-graphql-contract.md`
- `.dek/tasks/crm-ai-analysis-layer/FACTS.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`
- `.dek/changes/crm-opportunity-intelligence/TASKS.md`

Step 1: schema read/check

- Read only `/Users/yang/Desktop/CRM_schema.md` as the schema input.
- Record line-referenced facts for endpoint, root `Query`, root `Mutation`, v1 allow-listed query fields, and mutation presence.
- Do not access the real CRM endpoint.
- Do not read `.env.nanobot`.
- Do not copy schema examples containing token, secret, webhook, or robot URL text into docs or `.dek`.

Step 2: contract documentation

- Create `docs/crm-graphql-contract.md` with the GraphQL endpoint, v1 read-only query allow-list, forbidden mutation policy, query-to-normalized-model mapping, `SearchParam` to `ReportRequest` mapping, connection pagination rules, source reference rules, redaction rules, runtime config/env var design, and open questions.
- Keep the document free of real customer data, credentials, tokens, secrets, webhooks, and robot URLs.

Step 3: task split

- Replace the previous single RealCRMAdapter task with tasks 14A through 14F.
- Keep adapter implementation deferred until after this contract task.

Step 4: verification

- Run a local documentation check that asserts required sections exist in `docs/crm-graphql-contract.md` and required status notes exist in `.dek` artifacts.

## 14B. Extend normalized models for GraphQL-backed CRM data

Task: extend normalized CRM models only where the GraphQL contract requires additional fields for deterministic metrics.

Files touched:

- `nanobot/crm/models.py`
- `tests/crm/test_models.py`
- `tests/crm/test_graphql_normalization_contract.py`

Step 1: failing test

- Add tests for GraphQL source references, project-backed opportunity records, business-chance-backed opportunity records, activity context records, and money scalar normalization placeholders.
- Add tests proving model definitions still do not import HTTP clients, DingTalk modules, CLI modules, or real CRM clients.

Step 2: minimal implementation

- Add only the normalized fields required by `docs/crm-graphql-contract.md`.
- Preserve existing mock adapter behavior.
- Keep real GraphQL transport out of this task.

Step 3: verification

- Run `uv run --extra dev pytest tests/crm/test_models.py tests/crm/test_graphql_normalization_contract.py`
- Run `uv run --extra dev ruff check nanobot/crm/models.py tests/crm/test_models.py tests/crm/test_graphql_normalization_contract.py`

Step 4: cleanup/checkpoint

- Do not implement a GraphQL client or real adapter in this task.

## 14C. Implement GraphQL client shell with mocked transport (superseded for production route)

MCP-first status: completed historical/reference task. Do not expand this into production direct GraphQL access from Nanobot. Future production GraphQL transport belongs in the CRM MCP Server.

Task: add a fail-closed GraphQL client shell that can execute allow-listed queries through mocked transport only.

Files touched:

- `nanobot/crm/graphql_client.py`
- `tests/crm/test_graphql_client.py`

Step 1: failing test

- Add tests that allow-listed query names build query requests without network access.
- Add tests that non-allow-listed query names and every mutation operation are rejected before transport execution.
- Add tests that errors redact headers, tokens, cookies, secrets, and GraphQL variables.

Step 2: minimal implementation

- Implement a small client shell with an injected transport callable for tests.
- Keep runtime real endpoint calls disabled unless explicitly configured by later adapter work.
- Do not access the real CRM endpoint.

Step 3: verification

- Run `uv run --extra dev pytest tests/crm/test_graphql_client.py`
- Run `uv run --extra dev ruff check nanobot/crm/graphql_client.py tests/crm/test_graphql_client.py`

Step 4: cleanup/checkpoint

- Do not normalize business entities or implement `RealCRMAdapter` in this task.

## 14D. Implement RealCRMAdapter with mocked GraphQL responses (superseded for production route)

MCP-first status: completed historical/reference task. Do not continue this as the production real CRM adapter. Future production real CRM access belongs in the CRM MCP Server and should connect to Nanobot through `MCPCRMAdapter` or direct MCP tool usage.

Task: implement the read-only `RealCRMAdapter` behind the existing adapter interface using mocked GraphQL responses.

Files touched:

- `nanobot/crm/real_adapter.py`
- `nanobot/crm/graphql_client.py`
- `nanobot/crm/adapters.py`
- `tests/crm/test_real_adapter_contract.py`
- `tests/crm/test_real_adapter_normalization.py`

Step 1: failing test

- Add tests using synthetic mocked GraphQL responses for `listProject`, `projectInfo`, `list_business_chance`, `business_chance`, `listActivity`, `listCompany`, `companyInfo`, `listUser`, `listReport`, `reportInfo`, and `reportRelatedInfo` as needed by v1 metrics.
- Add tests proving the adapter satisfies `CRMAdapter.read_opportunities` without write-like methods.

Step 2: minimal implementation

- Implement read-only normalization from mocked GraphQL response shapes into normalized CRM models.
- Keep real endpoint access disabled by default.
- Preserve deterministic metric behavior.

Step 3: verification

- Run `uv run --extra dev pytest tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_normalization.py tests/crm`
- Run `uv run --extra dev ruff check nanobot/crm/real_adapter.py nanobot/crm/graphql_client.py nanobot/crm/adapters.py tests/crm/test_real_adapter_contract.py tests/crm/test_real_adapter_normalization.py`

Step 4: cleanup/checkpoint

- Do not use real CRM data or real CRM endpoint access in default tests.

## 14E. Add redaction and forbidden mutation tests (superseded)

MCP-first status: do not execute as written. Redaction and forbidden mutation tests move to the CRM MCP Server tasks below.

Task: harden the real adapter and GraphQL client against mutation use and sensitive data exposure.

Files touched:

- `nanobot/crm/graphql_client.py`
- `nanobot/crm/real_adapter.py`
- `tests/crm/test_real_adapter_redaction.py`
- `tests/crm/test_graphql_forbidden_mutation.py`

Step 1: failing test

- Add tests proving mutation operation strings and mutation-like operation names are rejected before transport execution.
- Add tests proving raw GraphQL payloads, headers, tokens, secrets, webhook URLs, robot URLs, cookies, and CRM response bodies are redacted from errors and logs.
- Add tests proving `.env.nanobot` is not read by tests or adapter construction.

Step 2: minimal implementation

- Add centralized redaction helpers only where needed.
- Ensure adapter errors expose stable sanitized categories.
- Keep all tests mocked and synthetic.

Step 3: verification

- Run `uv run --extra dev pytest tests/crm/test_real_adapter_redaction.py tests/crm/test_graphql_forbidden_mutation.py tests/crm`
- Run `uv run --extra dev ruff check nanobot/crm/graphql_client.py nanobot/crm/real_adapter.py tests/crm/test_real_adapter_redaction.py tests/crm/test_graphql_forbidden_mutation.py`

Step 4: cleanup/checkpoint

- Do not add write-capable CRM operations; any write capability requires a separate change proposal.

## 14F. Optional real CRM smoke test (superseded)

MCP-first status: do not execute as written. Real CRM smoke can only run through CRM MCP Server `crm_smoke_check` or an equivalent approved read-only MCP tool, with user-provided runtime environment outside chat.

Task: define an opt-in real CRM smoke test that is skipped by default and never runs in CI or local verification without explicit runtime configuration.

Files touched:

- `tests/crm/test_real_crm_smoke_optional.py`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: failing/skipped check

- Add a test that skips unless an explicit opt-in flag such as `NANOBOT_CRM_REAL_SMOKE=1` is set.
- The test must also require runtime endpoint and auth config to be present, but must never print those values.

Step 2: minimal implementation

- If the user approves real smoke execution later, run only a minimal allow-listed read query with a safe scope and record sanitized evidence.
- If not approved, keep the test skipped and document the required operator steps.

Step 3: verification

- Run `uv run --extra dev pytest tests/crm/test_real_crm_smoke_optional.py`
- Expected default result: skipped, with no network access.

Step 4: cleanup/checkpoint

- Do not run this against the real CRM unless the user explicitly approves endpoint access and provides runtime configuration through the environment outside chat.

## 15A. Design CRM MCP server

Task: write the detailed CRM MCP Server design from canonical docs without implementation code.

Files touched:

- `docs/crm/MCP_SERVER_DESIGN.md`
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: design check

- Confirm `docs/crm/README.md`, `docs/crm/GRAPHQL_CONTRACT.md`, `docs/crm/MCP_SERVER_DESIGN.md`, and `docs/crm/MCP_TOOL_CONTRACT.md` exist.
- Confirm the design states that real CRM GraphQL access belongs to the independent CRM MCP Server.
- Confirm the design states that Nanobot keeps mock/report/metrics/evidence and does not expand in-process `RealCRMAdapter`.

Step 2: design update

- Define CRM MCP Server responsibilities: read-only GraphQL client, Query allow-list, fixed selection sets, forbidden Mutation, pagination, redaction, sanitized diagnostics, and no raw payload logging.
- Define Nanobot connection options: `MCPCRMAdapter` or direct MCP tool usage through existing MCP configuration.
- Mark DingTalk deferred and CRM writeback out of scope.

Step 3: verification

- Run a documentation assertion checking the required sections and safety phrases.

Step 4: cleanup/checkpoint

- Do not write business code.
- Do not implement MCP server code.
- Do not access real CRM.

## 15B. Create MCP server skeleton with no real CRM access

Task: create a minimal CRM MCP Server project/package skeleton that cannot access real CRM.

Files touched:

- Future MCP server package files after user approval.
- Future MCP server tests.
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: failing test

- Add a test that starts or imports the skeleton without requiring CRM endpoint, credentials, `.env.nanobot`, or network access.
- Add a test proving the skeleton exposes no write-like tools.

Step 2: minimal implementation

- Add only MCP server skeleton code and static metadata.
- Keep real CRM runtime disabled and absent.

Step 3: verification

- Run the skeleton tests.
- Run lint for the new package/tests.

Step 4: cleanup/checkpoint

- No real CRM endpoint access.
- No credentials or auth headers in code/docs/tests.

## 15C. Implement read-only contract and forbidden mutation tests

Task: implement the MCP server read-only GraphQL contract with mocked transport only.

Files touched:

- Future MCP server contract/client/test files.
- `docs/crm/GRAPHQL_CONTRACT.md` only if contract wording needs clarification.
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: failing test

- Add tests proving only allow-listed Query operations can be built.
- Add tests proving every Mutation operation or mutation-like operation name is rejected before transport execution.
- Add tests proving fixed selection sets are used and raw ad hoc GraphQL is not exposed to Nanobot callers.

Step 2: minimal implementation

- Implement allow-list and selection-set construction against mocked transport only.
- Keep real endpoint access disabled.

Step 3: verification

- Run contract and forbidden mutation tests.
- Run lint for touched files.

Step 4: cleanup/checkpoint

- Do not add write-capable tools.
- Do not access real CRM.

## 15D. Implement `crm_smoke_check` with mocked transport

Task: add a read-only MCP diagnostic tool that can later become the only approved real CRM smoke path.

Files touched:

- Future MCP server tool and diagnostic tests.
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `docs/crm/MANUAL_TEST.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: failing test

- Add tests for `crm_smoke_check` with mocked transport.
- Assert output contains only safe fields such as status, read-only flag, mutation-used flag, allowed operation names, count, and sanitized categories.
- Assert no endpoint auth header, token, raw payload, customer detail, contact detail, amount, or free text is returned.

Step 2: minimal implementation

- Implement `crm_smoke_check` using mocked transport only.
- Return sanitized diagnostic categories.

Step 3: verification

- Run smoke-check tests.
- Run lint for touched files.

Step 4: cleanup/checkpoint

- Real smoke remains disabled until explicit user approval.

## 15E. Implement `crm_list_projects` with mocked GraphQL responses

Task: add the first read-only CRM MCP data tool using mocked GraphQL responses.

Files touched:

- Future MCP server project-list tool and tests.
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: failing test

- Add tests for `crm_list_projects` using synthetic mocked `listProject` responses.
- Add tests for scope/window/limit validation before transport.
- Add tests for pagination stop conditions and max-page limits.
- Add tests proving normalized output includes sanitized source references and no raw payloads.

Step 2: minimal implementation

- Implement `crm_list_projects` against mocked transport only.
- Normalize only fields needed by v1 reports or evidence traces.

Step 3: verification

- Run project-list tests.
- Run lint for touched files.

Step 4: cleanup/checkpoint

- Do not add non-allow-listed GraphQL operations.
- Do not access real CRM.

## 15F. Implement redaction and diagnostics tests

Task: harden the CRM MCP Server redaction and diagnostics boundary.

Files touched:

- Future MCP server redaction/diagnostics files and tests.
- `docs/crm/MANUAL_TEST.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: failing test

- Add tests proving credentials, endpoint auth headers, cookies, tokens, secrets, raw payloads, customer details, contact details, and unsupported free text are absent from outputs, errors, and logs.
- Add tests for stable diagnostic categories: config missing, CRM unavailable, unauthorized/forbidden, GraphQL error, pagination limit, normalization failed, empty result, and rate limited.

Step 2: minimal implementation

- Add centralized redaction and diagnostic mapping only where needed.
- Keep all tests mocked and synthetic.

Step 3: verification

- Run redaction and diagnostics tests.
- Run lint for touched files.

Step 4: cleanup/checkpoint

- Do not record real CRM output or secrets in evidence.

## 15G. Add Docker/stdio/HTTP MCP configuration docs

Task: document safe CRM MCP Server configuration modes without real credentials.

Files touched:

- `docs/crm/MANUAL_TEST.md`
- `docs/crm/MCP_SERVER_DESIGN.md`
- `docs/crm/MCP_TOOL_CONTRACT.md`
- Potential future Nanobot configuration docs after user approval.
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: documentation check

- Confirm docs cover stdio MCP, HTTP MCP, and Docker/Compose deployment options at a high level.
- Confirm examples use placeholders only and no auth headers with real values.

Step 2: minimal documentation

- Add safe configuration snippets only if needed.
- Keep credentials out of examples.

Step 3: verification

- Run documentation assertions for required sections and absence of forbidden secret markers.

Step 4: cleanup/checkpoint

- Do not read `.env.nanobot`.
- Do not run real CRM smoke.

## 15H. Wire Nanobot config to CRM MCP server in mock mode

Task: connect Nanobot to the CRM MCP Server in mock mode using existing MCP configuration.

Files touched:

- Future Nanobot config docs or tests.
- Future mock MCP server config fixtures.
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: failing test/check

- Add tests or config checks proving Nanobot can load CRM MCP server configuration in mock mode.
- Add tests or checks proving only approved tools are enabled.
- Add tests or checks proving no native built-in CRM tool registration is required.

Step 2: minimal implementation/configuration

- Wire mock-mode MCP config only.
- Keep real CRM runtime disabled.

Step 3: verification

- Run focused MCP config/tool-discovery tests or documented checks.
- Run lint for touched files if code changes are approved in that future task.

Step 4: cleanup/checkpoint

- No real CRM endpoint access.
- No credentials or auth headers in config fixtures.

## 15I. Optional real MCP smoke with user-provided env outside chat

Task: define and optionally run a real CRM MCP smoke only after explicit user approval.

Files touched:

- Future MCP smoke tests or scripts.
- `docs/crm/MANUAL_TEST.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: skipped-by-default check

- Add a smoke test that skips unless an explicit opt-in flag is set.
- Require runtime config from environment outside chat.
- Assert the smoke only calls `crm_smoke_check` or equivalent approved read-only MCP diagnostic.

Step 2: optional execution

- Run only if the user explicitly approves real CRM access for that session.
- Record only sanitized status, counts, operation names, and diagnostic categories.

Step 3: verification

- Default verification result must be skipped with no network access.
- Optional approved run must avoid printing real CRM data, endpoint auth headers, tokens, raw payloads, customer details, and contact details.

Step 4: cleanup/checkpoint

- Do not broaden the smoke beyond `crm_smoke_check` without a separate approval.

## 15J. Cleanup superseded RealCRMAdapter docs/code after user approval

Task: remove or archive superseded in-process direct GraphQL docs/code only after explicit user approval.

Files touched:

- To be determined after user approval.
- `docs/crm/DOCS_INVENTORY.md`
- `docs/crm/MIGRATION_NOTES.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`

Step 1: cleanup proposal

- List every candidate file or section.
- Confirm each unique fact has migrated to canonical `docs/crm/` docs or is intentionally dropped.
- Ask for explicit user approval before deletion or archival.

Step 2: minimal cleanup

- Only delete or archive files explicitly approved by the user.
- Preserve mock/report/metrics/evidence and mock CLI files unless explicitly approved otherwise.

Step 3: verification

- Run relevant tests after any code cleanup.
- Run documentation assertions after any doc cleanup.

Step 4: cleanup/checkpoint

- Do not perform this task without explicit user approval.

## 15K. Execute approved cleanup Option B: archive/mark superseded direct GraphQL docs

MCP-first status: Option B is approved. Execute documentation cleanup only. Keep `nanobot/crm/graphql_client.py`, `nanobot/crm/real_adapter.py`, and related direct-route tests as superseded reference material.

Task: mark old direct in-process GraphQL / `RealCRMAdapter` documentation as superseded so future agents do not treat it as the production route.

Files touched:

- `docs/crm-graphql-contract.md`
- `docs/crm/DOCS_INVENTORY.md`
- `docs/crm/MIGRATION_NOTES.md`
- `docs/crm/README.md`
- `.dek/changes/crm-opportunity-intelligence/TASKS.md`
- `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md`
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`
- Optional superseded-reference docstrings only in `nanobot/crm/graphql_client.py` and `nanobot/crm/real_adapter.py`

Step 1: documentation cleanup

- Strengthen the top notice in `docs/crm-graphql-contract.md`.
- Confirm `docs/crm/GRAPHQL_CONTRACT.md` remains canonical.
- Confirm the direct in-process GraphQL code/tests are retained reference material, not production CRM access expansion targets.

Step 2: verification

- Run CRM MCP Server tests, focused retained direct-route tests, lint for touched package/direct-route Python files, and safety assertions.

Step 3: cleanup/checkpoint

- Do not delete, move, or rename files.
- Do not change runtime behavior.
- Do not access real CRM, read `.env*`, run real smoke, connect DingTalk, or implement writeback/Mutation.

## Historical 15. Docker smoke test (completed before MCP-first route)

Task: verify Docker delivery can run the CRM CLI/report path without `.dek` or real secrets.

Files touched:

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `tests/docker/test_crm_docker_smoke.py`

Step 1: failing test/check

- Add or document a smoke check proving CRM report CLI works in mock mode inside the Docker delivery path.
- Add a check that Docker delivery does not require `.dek` as runtime input.
- Add a check that `.env.nanobot` and other secret-bearing env files are not baked into the image or read by smoke tests.

Step 2: minimal implementation

- Update Docker or Compose only if CRM runtime code, adapter service, or smoke command requires it.
- Update `.dockerignore` to exclude secret-bearing env files if needed.
- Keep CRM secrets as runtime configuration only.

Step 3: verification

- Run `pytest tests/docker/test_crm_docker_smoke.py`
- Run `docker compose config`
- Run `docker build -t nanobot-crm-smoke .`
- Run `docker run --rm nanobot-crm-smoke nanobot crm report daily --adapter mock --date 2026-01-15 --scope synthetic-team`

Step 4: cleanup/checkpoint

- If Docker/Compose files do not need changes, leave them untouched and keep the smoke test/documented command as the deliverable.

## 16. Review / QA / handoff

Task: run final QA, review implementation against spec/architecture, and update handoff artifacts.

Files touched:

- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`
- `.dek/changes/crm-opportunity-intelligence/TASKS.md`

Step 1: failing check

- Create an evidence checklist covering spec requirements, architecture principles, test commands, Docker smoke, DingTalk behavior, adapter read-only boundary, LLM boundary, evidence trace coverage, and safety/redaction.

Step 2: minimal implementation

- Run required verification commands and record results in `EVIDENCE.md`.
- Update `PROGRESS.md` with completed implementation status.
- Update `HANDOFF.md` with remaining decisions, known risks, and next operational steps.

Step 3: verification

- Run `pytest tests/crm tests/cli tests/tools tests/command tests/channels/test_crm_dingtalk_delivery.py tests/docker/test_crm_docker_smoke.py`
- Run `ruff check nanobot tests`
- Run `docker compose config`
- Run `python - <<'PY'
from pathlib import Path
evidence = Path('.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md').read_text()
required = ['pytest', 'ruff check', 'docker compose config', 'Docker', 'DingTalk', 'read-only', 'LLM', 'evidence trace', 'synthetic']
missing = [item for item in required if item not in evidence]
assert not missing, missing
PY`

Step 4: cleanup/checkpoint

- Do not commit unless explicitly requested by the user.
- Do not paste real CRM output, real customer data, tokens, or secrets into handoff artifacts.
