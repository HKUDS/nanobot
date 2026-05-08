# CRM Opportunity Intelligence Architecture

Change id: `crm-opportunity-intelligence`

## Context

Nanobot is the delivery host for a first-version CRM opportunity intelligence workflow. The existing self-developed CRM remains the source of record. This change adds a read-only analysis layer that turns CRM data into sales daily reports, sales weekly reports, and cross-sales opportunity dashboard summaries.

The first production slice should be narrow:

- Read mock CRM data through the existing Nanobot `CRMAdapter` boundary.
- Read real CRM data through a separate read-only CRM MCP Server.
- Compute metrics with deterministic Python code.
- Assemble reports with evidence traces.
- Use the LLM only for summarization, explanation, and recommendation text grounded in precomputed metrics and traces.
- Preserve mock CLI verification before any real CRM access.
- Defer DingTalk usage until the MCP server boundary and Nanobot MCP configuration are settled.

`.dek` files are development governance artifacts only. They must not become production runtime input, production output storage, report storage, CRM data cache, or deployment dependency.

## MCP-First Direction

The selected production direction is MCP-first.

- Real CRM GraphQL access is owned by an independent CRM MCP Server.
- Nanobot does not directly own real CRM GraphQL access for production.
- Nanobot does not expand the in-process `RealCRMAdapter` direct GraphQL path.
- Nanobot keeps the mock/report/metrics/evidence path for local development and deterministic report behavior.
- Future Nanobot-to-real-CRM connection should use either a thin `MCPCRMAdapter` or direct MCP tool usage through existing Nanobot MCP configuration.
- The old internal GraphQL client and `RealCRMAdapter` path is superseded and kept only as historical/reference material unless the user explicitly reopens it.
- Canonical CRM docs live under `docs/crm/`, especially `docs/crm/README.md`, `docs/crm/GRAPHQL_CONTRACT.md`, `docs/crm/MCP_SERVER_DESIGN.md`, and `docs/crm/MCP_TOOL_CONTRACT.md`.

## Constraints

- CRM access is read-only in v1.
- The system must not create, update, delete, assign, message, contact, or otherwise mutate CRM state.
- The report generator must not call CRM APIs directly.
- Nanobot's report generator must not call CRM GraphQL directly.
- The CRM MCP Server is the only production boundary that knows how the self-developed CRM GraphQL API is read.
- Nanobot's `CRMAdapter` boundary remains valid for mock data and may later be satisfied by `MCPCRMAdapter` or MCP tool usage.
- The first adapter implementation must be a mock adapter using synthetic data.
- Real CRM access comes through the CRM MCP Server after mock adapter, metrics, reports, CLI verification, and MCP contracts are approved.
- Do not continue expanding in-process `RealCRMAdapter` for production real CRM access.
- Metrics code is the only place where counts, totals, distributions, rankings, filtering, sorting, date-window selection, and status classification happen.
- The LLM must not calculate amounts, counts, percentages, distributions, date windows, risk classifications, rankings, or metric availability.
- Every key business conclusion must reference evidence trace data generated from deterministic metrics or stable CRM source references.
- CLI mock path remains the safe default verification surface.
- DingTalk CRM delivery is deferred.
- CRM writeback is out of scope and requires a separate change proposal.
- Real CRM smoke can only run through the CRM MCP Server's `crm_smoke_check` or equivalent approved read-only diagnostic tool, with user-provided runtime environment outside chat.
- Docker delivery must not depend on OpenCodeDEK or `.dek` files.
- `.dek` must not contain real CRM data, real customer data, tokens, secrets, generated production reports, or production runtime state.
- Tests and fixtures must use synthetic or mocked data only.
- Docker images must not bake CRM credentials or DingTalk secrets into the image.
- CRM-derived report generation must avoid persisting raw CRM records, real CRM-derived report content, or CRM-derived conversation history to Nanobot long-term memory or Claude-Mem.

## Components

### CRM Domain Models

Purpose: define the CRM-shaped data contract used inside Nanobot without exposing the real CRM schema throughout the codebase.

Responsibilities:

- Define v1 read entities and fields for opportunities, owners, pipeline stages, activity/change records, amounts, dates, status, and stable source references as needed by approved metrics.
- Represent report request scope, date windows, metric records, unavailable metric records, evidence traces, and report outputs.
- Keep domain objects independent from DingTalk, CLI, MCP, HTTP, database drivers, and LLM provider code.

Boundary:

- Domain models contain no network code and no CRM client code.
- Domain models may include redacted stable source references, but not secrets or unnecessary raw customer details.

### CRMAdapter Interface

Purpose: isolate mock and report-generation inputs behind a read-only adapter contract inside Nanobot.

Responsibilities:

- Expose only read methods required by v1 reports.
- Accept already-validated report scope and date window inputs.
- Return normalized domain records and stable source references.
- Return bounded error categories for unavailable CRM, invalid adapter configuration, and missing data.
- Avoid logging raw CRM payloads.

Boundary:

- The report generator depends on the `CRMAdapter` interface for local mock/report paths, not on HTTP clients, database drivers, GraphQL clients, or CRM-specific SDKs.
- No adapter method may create, update, delete, assign, message, contact, or otherwise mutate CRM state.

### Mock CRMAdapter

Purpose: enable the first vertical slice without real CRM credentials or real business data.

Responsibilities:

- Provide deterministic synthetic CRM records for unit tests and CLI verification.
- Cover normal data, empty data, missing metric inputs, multi-sales-user data, and edge cases.
- Use obviously fake names, identifiers, amounts, and dates.

Boundary:

- Mock data lives in tests or non-production synthetic fixture modules only.
- Mock fixture content must be labeled synthetic and must not resemble real customer records.

### Superseded In-Process RealCRMAdapter

Purpose: historical/reference path only. It must not be expanded as the production real CRM integration.

Responsibilities:

- Preserve existing mocked-transport tests and normalization learnings as reference material.
- Keep the completed code available until an approved cleanup task removes or archives it.
- Do not add production endpoint access, auth handling, direct real smoke, or broader direct GraphQL behavior in Nanobot.
- Treat `nanobot/crm/graphql_client.py`, `nanobot/crm/real_adapter.py`, and related direct-route tests as superseded references only.

Boundary:

- Superseded by the independent CRM MCP Server.
- Any future cleanup of in-process real adapter docs/code requires explicit user approval.

### CRM MCP Server

Purpose: own real CRM GraphQL access outside Nanobot.

Responsibilities:

- Provide a read-only GraphQL client.
- Enforce the query allow-list from `docs/crm/GRAPHQL_CONTRACT.md`.
- Use fixed selection sets for approved queries.
- Reject every Mutation operation before transport execution.
- Handle pagination with conservative limits and stop conditions.
- Redact credentials, auth headers, raw payloads, contact details, and unsupported free text.
- Provide sanitized diagnostics and stable error categories.
- Avoid raw payload logging.
- Expose only approved read-only MCP tools, including `crm_smoke_check` or an equivalent smoke diagnostic.

Boundary:

- CRM credentials and auth headers belong to the MCP server runtime, not Nanobot.
- Raw GraphQL payloads must not cross from the MCP server into Nanobot.
- MCP server tests must use mocked transport and synthetic GraphQL responses by default.

### MCPCRMAdapter Or MCP Tool Usage

Purpose: connect Nanobot to the CRM MCP Server without embedding CRM GraphQL access in Nanobot.

Responsibilities:

- Use existing Nanobot MCP configuration to call the CRM MCP Server.
- Optionally provide a thin `MCPCRMAdapter` that satisfies Nanobot report-generation boundaries from MCP tool results.
- Preserve existing mock CLI behavior and deterministic metrics.
- Keep MCP connection errors sanitized and mapped to stable categories.

Boundary:

- No direct GraphQL endpoint, auth header, token, cookie, or raw payload handling in Nanobot.
- No native built-in CRM tool registration unless a future approved plan proves existing MCP configuration is insufficient.

### Metrics Layer

Purpose: produce all numeric and classified business facts with deterministic code.

Responsibilities:

- Validate report windows and scope.
- Filter normalized CRM records by date/window/scope.
- Compute counts, totals, distributions, movement summaries, stalled/risk labels, win/loss summaries, owner/team aggregations, and unavailable metric markers.
- Produce metric records with metric name, value, input scope, date/window, calculation id, source references, and missing inputs when applicable.
- Never call the LLM.

Boundary:

- Metrics layer may use CRM domain records from an adapter result.
- Metrics layer must not call CRM APIs directly.
- Metrics layer must not depend on CLI, DingTalk, channel code, or Nanobot memory code.

### Evidence Trace Builder

Purpose: record why each key conclusion exists.

Responsibilities:

- Create trace ids for metric-backed conclusions.
- Link report statements to metric records, source entity types, stable source references, field names, report scope, and calculation identifiers.
- Redact or omit secrets, raw CRM payloads, and unnecessary raw customer details.
- Provide trace records in report-local output rather than `.dek` or long-term memory.

Boundary:

- Evidence traces are report artifacts, not production `.dek` artifacts.
- Trace records must be generated from synthetic data in tests.

### Report Generator

Purpose: orchestrate report creation without knowing CRM implementation details.

Responsibilities:

- Accept a report request for daily, weekly, or dashboard output.
- Validate caller-provided or explicitly configured date/window and scope.
- Fetch normalized data through `CRMAdapter` only.
- Call metrics layer for all numeric and classified facts.
- Build evidence traces for key conclusions.
- Build prompt-safe LLM input that distinguishes metric values, direct CRM source fields, unavailable metric markers, and trace ids.
- Assemble final report sections, deterministic fallback output, and error output.

Boundary:

- Report generator does not call CRM API clients directly.
- Report generator does not let the LLM decide dates, filters, rankings, classifications, missing metrics, or calculations.
- Report generator can run without LLM by returning deterministic sections and evidence traces.

### LLM Narrative Adapter

Purpose: constrain LLM usage to language work.

Responsibilities:

- Accept precomputed metrics, unavailable metric markers, trace ids, and bounded source references.
- Request concise summaries, explanations, and suggestions grounded in supplied evidence.
- Reject or flag generated narrative containing numbers, labels, trends, or claims not present in metric records, direct source fields, unavailable markers, or evidence traces.
- Return a deterministic fallback path when LLM summarization fails.

Boundary:

- No raw CRM payloads, credentials, tokens, or full sensitive prompts should be logged.
- No LLM response is treated as a source of truth for metrics.

### CLI Entry

Purpose: provide the first operational and testable entry point.

Responsibilities:

- Trigger daily report, weekly report, and dashboard summary generation using mock or configured adapter mode.
- Return deterministic exit status.
- Print sanitized terminal output with report sections and evidence traces.
- Support synthetic/mock verification without CRM secrets.

Boundary:

- CLI delegates to report generator.
- CLI does not embed CRM client logic, metrics logic, or DingTalk delivery logic.
- Prefer adding a focused CRM CLI command only if `nanobot agent -m` cannot provide repeatable verification; otherwise use existing agent CLI plus configured tools/instructions.

### DingTalk Entry

Purpose: deferred daily usage surface after the MCP server boundary and Nanobot MCP configuration are settled.

Responsibilities:

- Keep existing DingTalk transport behavior unchanged in the MCP planning phase.
- Reuse existing Nanobot message/channel delivery paths only after a future DingTalk task is approved.
- Include inline trace ids or a report-local evidence trace section when DingTalk delivery is later implemented.
- Surface delivery failures with sanitized error categories when DingTalk delivery is later implemented.

Boundary:

- Do not add CRM-specific report logic to `nanobot/channels/dingtalk.py`.
- Do not expose CRM mutation controls, approval actions, customer-contact actions, or ad hoc BI query controls.
- Do not implement DingTalk while the current work is MCP server design/configuration.

### Configuration And Runtime Policy

Purpose: keep production runtime independent from `.dek` and keep secrets out of images and logs.

Responsibilities:

- Configure adapter mode, report scope defaults, runtime credentials, DingTalk destination, and optional schedules through runtime config or environment, not `.dek`.
- Keep `.dek` out of runtime dependency paths.
- Ensure report generation does not persist CRM-derived content into long-term memory.

Boundary:

- `.dek` contains plans and specs only.
- Production report requests and outputs use runtime configuration and channel/session mechanisms, not `.dek` storage.

## File structure

Preferred in-process structure if this repository owns the report generator:

```text
nanobot/crm/
  __init__.py
  adapters.py          # CRMAdapter protocol/interface and adapter errors
  models.py            # Domain request, source record, metric, trace, report models
  mock_adapter.py      # Synthetic read-only adapter for tests and CLI verification
  metrics.py           # Deterministic metric computation only
  evidence.py          # Evidence trace construction and redaction helpers
  reports.py           # Report generator orchestration
  llm.py               # LLM narrative adapter and narrative validation
  cli.py               # CRM CLI command helpers, if a dedicated command is added
```

Nanobot keeps this in-process CRM package for mock/report/metrics/evidence:

- `nanobot/crm/models.py`
- `nanobot/crm/mock_adapter.py`
- `nanobot/crm/metrics.py`
- `nanobot/crm/evidence.py`
- `nanobot/crm/reports.py`
- mock CLI helpers and command wiring

The in-process real GraphQL files are not the production expansion path.

Preferred tests:

```text
tests/crm/
  test_mock_adapter.py
  test_metrics_daily.py
  test_metrics_weekly.py
  test_metrics_dashboard.py
  test_evidence.py
  test_reports.py
  test_llm_boundary.py
  test_safety.py

tests/cli/
  test_crm_cli.py       # Only if a dedicated CLI command is added

tests/channels/
  test_crm_dingtalk_delivery.py  # Only for CRM-specific routing/delivery behavior
```

Preferred external CRM MCP Server structure if this repository owns the server:

```text
crm_mcp_server/
  README.md
  pyproject.toml
  crm_mcp_server/
    __init__.py
    server.py           # MCP or service entry point
    graphql_client.py   # Read-only GraphQL client
    contract.py         # Query allow-list, fixed selection sets, tool contracts
    redaction.py
    diagnostics.py
  tests/
```

Existing files to avoid modifying unless needed:

- `nanobot/agent/loop.py`: avoid registering CRM as built-in tools unless MCP/configured tool path is insufficient.
- `nanobot/channels/dingtalk.py`: avoid CRM report logic in transport code.
- `nanobot/agent/memory.py`: avoid memory core changes unless scoped policy/config cannot prevent CRM persistence.
- `nanobot/config/schema.py`: avoid first-class global config unless runtime config cannot be expressed through existing mechanisms.
- `docker-compose.yml`: change only if the adapter needs an additional service or explicit wiring.

## Data flow

### CLI-first flow

1. Developer runs the CRM report path with report type, date/window, scope, and adapter mode.
2. CLI validates required inputs or resolves explicitly configured defaults.
3. CLI constructs a report request and calls the report generator.
4. Report generator reads normalized records through `CRMAdapter`.
5. Mock adapter returns synthetic records for first implementation and tests.
6. Future real CRM data comes through the CRM MCP Server and either an `MCPCRMAdapter` or direct MCP tool usage.
7. Metrics layer computes all numeric values, classifications, movement summaries, unavailable markers, and metric records.
8. Evidence trace builder links key conclusions to metric records and source references.
9. Report generator builds prompt-safe LLM input from metrics, direct source fields, unavailable markers, and trace ids.
10. LLM narrative adapter creates grounded text or returns a deterministic fallback on failure.
11. Report generator assembles fixed report sections and evidence trace section.
12. CLI prints sanitized output and exits with deterministic status.

### DingTalk flow

DingTalk CRM delivery is deferred. The historical desired flow is retained for reference only and must not be implemented until the MCP server and Nanobot MCP connection are settled.

1. DingTalk user or configured schedule requests a daily report, weekly report, or dashboard summary.
2. DingTalk-facing command or workflow maps the request to the same report request model used by CLI.
3. Report generator executes the same adapter, metrics, evidence, and LLM flow used by CLI.
4. Output is sent through existing Nanobot outbound message routing to `channel="dingtalk"` and a configured `chat_id` or destination.
5. DingTalk receives report content with inline trace ids or a report-local evidence trace section.
6. Delivery errors return sanitized error categories; no CRM write retry exists because v1 has no CRM write path.

### Error flow

1. Invalid date/window/scope returns validation error before CRM read or LLM call.
2. CRM unavailable returns a CRM read failure category without fabricated report content.
3. Empty data returns a no-data report or no-data message for the requested scope/window.
4. Missing metric inputs produce unavailable metric markers and suppress unsupported conclusions.
5. LLM failure returns deterministic metrics, unavailable markers, and evidence traces without invented narrative.
6. DingTalk failure surfaces delivery failure without CRM mutation or unsafe retry behavior.

### MCP real CRM flow

1. Nanobot runtime config connects to the CRM MCP Server through stdio, HTTP, or another approved MCP transport.
2. Nanobot calls approved read-only MCP tools such as report-facts tools, project-list tools, or `crm_smoke_check`.
3. The MCP server validates request shape, scope, date/window, and limit values before CRM access.
4. The MCP server maps the tool request to fixed allow-listed GraphQL `Query` operations and fixed selection sets.
5. The MCP server rejects Mutation and non-allow-listed operations before transport execution.
6. The MCP server paginates conservatively and normalizes results.
7. The MCP server redacts and returns sanitized records, metrics, source refs, diagnostics, or error categories.
8. Nanobot uses the safe MCP output with existing report/metrics/evidence behavior or returns sanitized diagnostics.

## Test strategy

Testing starts with existing mock/report behavior and mocked MCP server behavior. Real CRM smoke is opt-in only through the MCP server.

### Unit tests

- `CRMAdapter` contract tests prove the mock adapter exposes only read behavior and returns normalized synthetic records.
- Metrics tests cover daily, weekly, and dashboard calculations with synthetic records.
- Metrics tests verify counts, amounts, distributions, movement labels, risk/stalled labels, and missing-input markers are deterministic.
- Evidence tests verify each key conclusion references an existing trace id or trace record.
- Report generator tests verify fixed sections, no-data output, unavailable metrics, sanitized errors, and deterministic fallback output.
- LLM boundary tests use a stubbed LLM to verify narrative containing unsupported numbers, labels, trends, or claims is rejected or flagged.
- Safety tests verify report generation does not write CRM data to `.dek`, test fixtures, logs, Claude-Mem, or long-term memory paths.

### CLI tests

- CLI can generate daily report using mock adapter and synthetic data.
- CLI can generate weekly report using mock adapter and synthetic data.
- CLI can generate dashboard summary using mock adapter and synthetic data.
- CLI returns deterministic exit status for success, validation error, no-data, missing metrics, CRM unavailable, and LLM failure.
- CLI output is sanitized and includes trace ids or evidence section.

### DingTalk tests

- DingTalk integration is tested only after CLI path passes.
- Tests use mocks for channel delivery and synthetic report data.
- Tests verify the request maps to the same report generator used by CLI.
- Tests verify output stays inside configured report scope and includes trace ids or evidence section.
- Tests verify no CRM mutation controls, approval actions, customer-contact actions, or ad hoc BI controls are exposed.
- Existing DingTalk transport tests should not be duplicated unless generic transport behavior changes.

### Adapter tests

- Mock adapter tests come first and require no secrets.
- In-process `RealCRMAdapter` direct GraphQL tests are superseded for production direction and retained only as historical/reference coverage.
- `MCPCRMAdapter` or MCP tool usage tests must use mocked MCP server responses by default.
- Tests must prove write, task creation, assignment, delete, message, customer-contact, export, and writeback operations are absent or disabled.

### CRM MCP Server tests

- Contract tests for approved MCP tool names, inputs, outputs, and error categories.
- GraphQL allow-list tests proving only approved Query operations can execute.
- Fixed selection set tests proving raw ad hoc GraphQL is not exposed.
- Forbidden Mutation tests proving Mutation operations are rejected before transport execution.
- Pagination tests for page size, max page, empty page, and limit stop conditions.
- Redaction tests proving credentials, auth headers, raw payload markers, contact details, and unsupported free text are absent from outputs/errors/logs.
- Sanitized diagnostics tests for config missing, unavailable, unauthorized/forbidden, GraphQL error, pagination limit, normalization failure, and empty result categories.
- `crm_smoke_check` tests using mocked transport by default.

### Docker and configuration checks

- If Dockerfile changes, run Docker build smoke verification.
- If Compose changes, run Compose config verification.
- Confirm Docker build context and image do not require `.dek`, CRM secrets, or DingTalk secrets.
- Confirm `.env.nanobot` and other secret-bearing env files are not read during tests or baked into images.
- Future Docker/stdio/HTTP MCP configuration docs must avoid real credentials and auth headers.

### Suggested verification commands

- `pytest tests/crm`
- `pytest tests/cli` if a dedicated CLI command is added.
- MCP server contract/redaction/diagnostics tests once server skeleton exists.
- MCP mock-mode Nanobot wiring tests once `MCPCRMAdapter` or direct MCP tool usage exists.
- `pytest tests/channels/test_crm_dingtalk_delivery.py` only if CRM-specific DingTalk tests are later approved.
- `ruff check nanobot/`
- `docker compose config` if `docker-compose.yml` changes.
- `docker build -t nanobot .` if Dockerfile or packaged dependencies change.

## Risks

- Real CRM schema may not provide stable source references needed for evidence traces.
- CRM fields required by v1 metrics may be missing, inconsistent, or semantically ambiguous.
- DingTalk recipient scope remains deferred and may later cause data exposure risk if group/user targets are not configured precisely.
- Default Nanobot session or memory behavior may persist CRM-derived conversation content unless CRM workflows explicitly bypass or disable long-term memory persistence.
- LLM narrative may introduce unsupported claims unless narrative validation is implemented and tested.
- MCP or external adapter deployment may add Docker/Compose complexity.
- Native in-process adapter implementation is superseded for production real CRM access because it reduces isolation and increases the chance of CRM-specific code leaking into generic Nanobot runtime paths.
- `.env.nanobot` is referenced by Compose and should be treated as sensitive; implementation should avoid reading it and consider Docker build context exclusion if needed.
- Report schedules and timezones are still product decisions and should not be inferred by the LLM.

## Docker deployment notes

- Docker delivery must work without `.dek` files.
- `.dek` remains a planning/specification directory and must not be mounted or read as production report configuration.
- Runtime configuration should come from Nanobot config, environment variables, mounted workspace config, or adapter-specific runtime config that contains no checked-in secrets.
- CRM credentials and DingTalk credentials must be runtime secrets, not Docker image contents.
- If using an external CRM MCP Server, prefer a separate Compose service or separately deployed internal endpoint with an explicit allow-list of read tools.
- If using stdio MCP inside the Nanobot container, package only the adapter runtime code and configure it at runtime; do not package `.dek` as an input.
- Do not add in-process direct CRM GraphQL runtime dependencies to Nanobot for production real CRM access.
- `docker-compose.yml` should change only when an adapter service, adapter network wiring, or explicit runtime environment wiring is required.
- Docker verification should include build or Compose checks only when Docker or Compose files change.

## DingTalk integration notes

- DingTalk integration is deferred.
- Future DingTalk integration follows MCP server implementation, Nanobot MCP configuration, CLI/mock verification, and explicit user approval.
- Use existing DingTalk channel transport for send/receive behavior.
- CRM report generation should not be implemented in `nanobot/channels/dingtalk.py`.
- Prefer routing generated reports through existing outbound message mechanisms with `channel="dingtalk"` and a configured destination.
- V1 supports only daily report, weekly report, and dashboard summary request/delivery.
- Scheduled DingTalk delivery is allowed only for those same report outputs and only after schedule, timezone, and recipient scope are explicitly configured.
- DingTalk output must include trace ids inline or a report-local evidence section.
- DingTalk output must stay within configured report scope and recipient context.
- DingTalk must not expose CRM mutation controls, approval actions, customer-contact actions, automatic task creation, automatic assignment, or ad hoc BI query controls.
- DingTalk delivery failure must surface a sanitized delivery error and must not trigger CRM writes or unsafe retries.

## CRM adapter notes

- `CRMAdapter` remains the hard boundary for Nanobot mock/report inputs.
- The CRM MCP Server is the hard boundary around real CRM GraphQL access.
- The report generator, metrics layer, CLI, future DingTalk workflow, and LLM adapter depend on normalized domain models or sanitized MCP output, not on CRM API details.
- Start with `MockCRMAdapter` using synthetic data.
- Do not continue expanding the in-process `RealCRMAdapter` direct GraphQL path for production.
- Implement future real CRM access in the CRM MCP Server after MCP design/tool contracts are approved.
- Add `MCPCRMAdapter` or direct MCP tool usage only as a Nanobot-to-MCP connection layer.
- The CRM MCP Server must expose only read operations needed by v1.
- The CRM MCP Server must enforce the v1 data contract allow-list for entities and fields.
- The CRM MCP Server must return stable source references for evidence traces.
- The CRM MCP Server must avoid logging raw CRM payloads and must sanitize errors.
- MCP server and adapter configuration must not require secrets in `.dek`, tests, fixtures, Docker images, or chat history.
- Real CRM smoke can only run through `crm_smoke_check` or an equivalent approved MCP tool.
- Any future write-capable CRM integration must be a separate change proposal and is out of scope for this architecture.
