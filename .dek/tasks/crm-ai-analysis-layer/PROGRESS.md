# Progress

Task id: `crm-ai-analysis-layer`

## Current State

- Task directory created at `.dek/tasks/crm-ai-analysis-layer/`.
- Claude-Mem recall skipped per user instruction.
- Project structure, Dockerfile, compose file, CLI entry points, test commands, and extension mechanisms inspected without reading `.env*`, tokens, secrets, or real CRM/customer data.
- Confirmed facts written to `FACTS.md`.
- Initial plan written to `PLAN.md`.
- Task 14D complete: `RealCRMAdapter` now normalizes mocked GraphQL responses for projects/opportunities, activities, reports, customers, and business chances through the injected GraphQL client shell, with pagination variables and sanitized error mapping covered by tests.
- Direction changed: real CRM access should no longer continue through an in-process Nanobot `RealCRMAdapter` that talks directly to GraphQL. The selected direction is a separate read-only CRM MCP Server as the real CRM access layer.
- Documentation convergence audit complete: `docs/crm/DOCS_INVENTORY.md` now classifies CRM-related docs and task artifacts as Canonical, Superseded, Deferred, or Remove later candidate.
- Canonical CRM documentation directory established under `docs/crm/`: `README.md`, `GRAPHQL_CONTRACT.md`, `MCP_SERVER_DESIGN.md`, `MCP_TOOL_CONTRACT.md`, `MANUAL_TEST.md`, `MIGRATION_NOTES.md`, and updated `DOCS_INVENTORY.md`.
- `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` and `TASKS.md` updated to MCP-first route: real CRM GraphQL access belongs to a separate CRM MCP Server, Nanobot keeps mock/report/metrics/evidence, and the direct in-process `RealCRMAdapter` path is superseded for production.
- `docs/crm/MANUAL_TEST.md` Docker Mock Smoke Compose guidance corrected to prefer `docker compose config --quiet` and avoid recording Compose-expanded environment output.
- Task 15B complete: independent `crm_mcp_server/` package skeleton exists with static server metadata, v1 read-only tool names, tests blocking write-like tools, and real CRM access disabled by default.
- Task 15C complete: CRM MCP Server now has a static read-only GraphQL operation contract with canonical v1 Query allow-list, fixed selection-set construction, forbidden Mutation checks, write-like operation-name rejection, no raw GraphQL passthrough, and no network transport.
- Task 15D complete: `crm_smoke_check` exists as a read-only mocked-transport diagnostic tool returning only sanitized status, boundary flags, allow-listed operation names, count fields, reason, and sanitized error categories.
- Task 15E complete: `crm_list_projects` exists as the first read-only mocked GraphQL data tool, validating requests before transport, using fixed `listProject`, paginating with caps, and returning sanitized project records/source refs/diagnostics only.
- Task 15F complete: CRM MCP Server redaction and diagnostics are hardened with shared safe error helpers, uniform ToolError shape, diagnostics allow-lists, cross-tool sensitive marker tests, and source safety assertions.
- Task 15G complete: `docs/crm/MCP_CONFIGURATION.md` now documents future-only Docker, stdio MCP, HTTP MCP, token-handling, allowed-tool, forbidden-tool, and safe verification guidance. Verification passed via CRM MCP tests, ruff, and docs safety assertion through `uv run python`. No runtime code or real CRM access was added.
- Task 15H complete: `docs/crm/examples/nanobot-crm-mcp.mock.yaml` now provides a mock-mode Nanobot MCP config example parsed by the real `Config` schema, enabling only `crm_smoke_check` and `crm_list_projects` with no CRM credentials, explicit local env-file path, real endpoints, or write-like tools. Focused config tests, CRM MCP tests, ruff, and docs safety assertion passed.
- Task 15I complete with inconclusive real-smoke status: optional real smoke module exists and is covered by mocked unit tests. Package-local real smoke command returned sanitized `INCONCLUSIVE/config_missing`, meaning this OpenCode process did not receive runtime CRM config outside chat. No real CRM request was made.
- Task 15J phase-one cleanup review complete: `docs/crm/REAL_ADAPTER_CLEANUP_REVIEW.md` inventories superseded direct GraphQL / `RealCRMAdapter` docs, code, tests, and task artifacts without deleting, moving, renaming, or changing runtime code. Recommended current choice is Option B: archive or strongly mark superseded docs first, while keeping direct adapter code/tests as reference until the MCP path proves stable.
- Task 15J Option B cleanup complete: `docs/crm-graphql-contract.md` is archived in place with a strong superseded-reference header. Direct adapter code/tests remain in place as reference material.
- Task 15K Option B cleanup complete: superseded direct GraphQL docs and direct-route Python module docstrings are marked reference-only, `docs/crm/` remains canonical, CRM MCP Server remains the production real CRM access direction, and direct adapter code/tests are retained as reference/safety material.
- Task 16A complete: `crm_list_business_chances` is implemented as a read-only mocked GraphQL data tool using fixed allow-listed `list_business_chance`, sanitized minimal records/source refs/errors/diagnostics, validation-before-transport, pagination caps, and sensitive-output tests.
- Task 16B complete: `crm_generate_daily_report_facts` is implemented as a read-only mocked report-facts composer using injected `crm_list_projects`/`crm_list_business_chances`-style dependency outputs, deterministic daily metrics, sanitized unavailable metrics, deduped source refs, and sensitive-output tests.
- Task 15I real-smoke diagnostics refined: sanitized smoke fields now distinguish transport attempted, JSON parse status, data root presence, operation data presence, records field presence/list-ness, reported total, counts, safe reason, and safe HTTP category. Real smoke now returns consistent sanitized `ERROR/crm_unavailable` with `runtime_enabled=true` and `transport_attempted=true`, not `empty_result`.
- Task 15I-fix complete: real-smoke transport diagnostics now include safe `transport_error_category`, `status_code_category`, endpoint/token/proxy configured booleans, and non-JSON/HTTP/network category mapping. Current real smoke is sanitized `transport_error_category=http_4xx`, `status_code_category=4xx`, `proxy_configured=false`.
- Task 15I-fix GraphQL diagnostics complete: local `crm_graphql_templates_all.md` was used only as a reference for sanitized `listProject` shape facts, and real-smoke GraphQL errors now emit safe `graphql_error_category`, `graphql_error_path_present`, and `graphql_error_extensions_present`. Current real smoke is HTTP success + JSON parsed + `graphql_error_category=graphql_unknown_error`, with path present and extensions absent.
- Task 15I-fix local-only inspection mode complete: default smoke remains sanitized; explicit `--inspect-graphql-error-local` can print redacted GraphQL error messages locally with warning text and no file writes. Raw inspection output was not run or recorded.
- Task 15I-fix auth diagnostics complete: `--auth-mode` supports `private_token`, `bearer`, and `cookie`; sanitized auth-mode smoke checks show `bearer` succeeds with `status=OK`, `data_count=1`, `graphql_errors_count=0`, while `private_token` and `cookie` return sanitized `auth_error_category=not_login`.
- Task 15I-followup complete: real smoke now uses `bearer` as the documented/default CRM GraphQL auth mode; `private_token` and `cookie` remain explicit optional diagnostics.
- Task 15I-fix closeout complete: default sanitized real smoke succeeded with `status=OK`, `reason=ok`, `auth_mode=bearer`, `runtime_enabled=true`, `status_code_category=2xx`, `data_count=1`, `normalized_count=1`, `reported_total=703`, `graphql_errors_count=0`, `mutation_used=false`, and `errors=[]`.
- Task 17A complete: `crm_list_projects` now supports default network-free mock/injected transport mode and explicit `runtime_enabled=true` real mode using the sanitized bearer real transport behind complete runtime config. Verification passed with focused tests, full CRM MCP tests, and ruff.
- Task 17B complete: `crm_list_business_chances` now supports default network-free mock/injected transport mode and explicit `runtime_enabled=true` real mode using the sanitized bearer real transport behind complete runtime config. Verification passed with focused tests, full CRM MCP tests, and ruff. No real business-chance check was run.
- Final review fixes complete: confirmation package preparation now sanitizes string `target` and string-list `to` entries before signing/serialization, and stdio MCP registration uses `@server.call_tool(validate_input=False)` so runtime sanitization handles invalid inputs instead of SDK validation echo paths. Requested focused tests, full CRM MCP tests, ruff, and config tests passed.
- No runtime behavior was changed in 15K. No MCP server production wiring was changed. No files were deleted, moved, or renamed. `.env*` was not read. No real CRM endpoint was accessed.

## Completed

- Checked project structure.
- Checked Dockerfile and Docker Compose configuration.
- Checked testing commands and package scripts.
- Checked skills, tools, channels, providers, memory, cron/heartbeat, MCP, and DingTalk extension mechanisms.
- Checked CLI entry point and top-level commands.
- Wrote initial task files.
- Completed task 1 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Confirm Nanobot extension points.
- Completed task 2 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Define standard CRM data model.
- Completed task 3 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Create mock CRM fixture.
- Completed task 4 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Create CRMAdapter interface.
- Completed task 5 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement MockCRMAdapter.
- Completed task 6 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement pipeline metrics.
- Completed task 7 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement daily report.
- Completed task 8 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement weekly report.
- Completed task 9 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement dashboard summary.
- Completed task 10 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement CLI.
- Completed task 11 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Connect Nanobot tool/skill using the MCP-first skill path.
- Completed task 12 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement DingTalk fixed command.
- Completed task 13 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement evidence trace.
- Task 14 from `.dek/changes/crm-opportunity-intelligence/TASKS.md` remains deferred pending user confirmation of the real CRM read interface and allowed field/source-reference contract.
- Completed task 14A from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Extract GraphQL read contract.
- Completed task 14B from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Extend normalized models for GraphQL-backed CRM data.
- Completed task 14C from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement GraphQL client shell with mocked transport.
- Completed task 14D from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement RealCRMAdapter with mocked GraphQL responses.
- Completed task 15 from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Docker smoke test.
- Completed documentation convergence audit for the MCP route and created `docs/crm/DOCS_INVENTORY.md`.
- Completed canonical CRM docs convergence under `docs/crm/` for the future MCP server design and implementation entry point.
- Marked `docs/crm-graphql-contract.md` as superseded by `docs/crm/GRAPHQL_CONTRACT.md` without deleting it.
- Updated `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` with MCP-first architecture, CRM MCP Server responsibilities, `MCPCRMAdapter`/MCP tool usage connection layer, deferred DingTalk, CRM writeback out of scope, and MCP-only real smoke boundary.
- Updated `.dek/changes/crm-opportunity-intelligence/TASKS.md` with new future tasks 15A through 15J and superseded status for the direct `RealCRMAdapter` GraphQL route.
- Completed small documentation safety correction in `docs/crm/MANUAL_TEST.md`: optional Compose syntax check now uses `docker compose config --quiet` and warns against running or recording plain `docker compose config` output unless secret-safe.
- Completed task 15B from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Create MCP server skeleton with no real CRM access.
- Completed task 15C from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement read-only contract and forbidden mutation tests with mocked transport only.
- Completed task 15D from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement `crm_smoke_check` with mocked transport.
- Completed task 15E from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement `crm_list_projects` with mocked GraphQL responses.
- Completed task 15F from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Implement redaction and diagnostics tests.
- Completed task 15G from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Add Docker/stdio/HTTP MCP configuration docs.
- Completed task 15H from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Wire Nanobot config to CRM MCP server in mock mode.
- Completed task 15I from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Optional real MCP smoke with user-provided env outside chat, with result `INCONCLUSIVE/config_missing` in this OpenCode process.
- Completed task 15J phase one from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: Cleanup superseded RealCRMAdapter docs/code review and inventory proposal only. No deletion, archive, move, rename, runtime-code change, or test skip was performed.
- Completed task 15J Option B from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: archived superseded root GraphQL doc in place and updated cleanup docs/status. No file was deleted, moved, or renamed; direct adapter code/tests were not edited.
- Completed task 15K from `.dek/changes/crm-opportunity-intelligence/TASKS.md`: executed approved Option B cleanup by strengthening superseded-reference docs and module docstrings while retaining direct adapter code/tests.
- Completed task 16A: Implement `crm_list_business_chances` with mocked GraphQL responses.
- Completed task 16B: Implement `crm_generate_daily_report_facts` backed by mocked CRM MCP read-tool outputs.
- Completed 15I real-smoke sanitized diagnostic classification refinement and reran the approved real smoke command once.
- Completed 15I-fix: added sanitized transport diagnostics and reran the approved real smoke command once.
- Completed 15I-fix GraphQL layer safe categorization and reran the approved real smoke command once.
- Completed 15I-fix local-only raw GraphQL error inspection command, without running inspect mode.
- Completed 15I-fix sanitized auth strategy diagnostics; bearer auth is the working real-smoke mode for the current runtime token.
- Completed 15I-followup: made bearer the default real-smoke auth mode and updated CRM docs plus `.dek` handoff artifacts.
- Completed 15I-fix closeout: recorded sanitized successful real smoke result and reran CRM MCP tests plus ruff.
- Completed 17A implementation and verification.
- Completed 17B implementation and verification.
- Completed final review fixes for confirmation redaction and MCP SDK validation bypass.

## Pending

- User decision whether to push branch / PR after final review fixes.
- Recommended 17C: add a dedicated approved sanitized real business-chance smoke/helper if `list_business_chance` shape needs validation, or proceed to real-mode daily report facts only after that read path is explicitly verified.
- Keep WebUI and DingTalk deferred; do not jump there before the real `crm_list_projects` transport path is safely integrated.
- Future user decision only if deeper cleanup is desired after Option B/15K. Direct adapter code/tests remain superseded-reference material.
- Option C remains deferred until MCP tools cover equivalent behavior and the user explicitly approves removal.
- Current real smoke default is bearer auth and the sanitized 15I minimum read-only default-command smoke has succeeded.
- Do not paste or commit local inspection output.
- DingTalk CRM delivery remains deferred until the CRM MCP Server contract and Nanobot MCP configuration are settled.

## Superseded By MCP Route

- Do not proceed with Task 14E or 14F as written in `.dek/changes/crm-opportunity-intelligence/TASKS.md`; those tasks continue the internal GraphQL client/`RealCRMAdapter` route.
- Keep the completed internal adapter work as historical/reference material only unless the user explicitly reopens that route.
- Use `docs/crm/GRAPHQL_CONTRACT.md` as the canonical GraphQL source contract for the future CRM MCP Server.
- Keep `docs/crm-graphql-contract.md` as an archived-in-place superseded migration-reference file.
- `nanobot/crm/graphql_client.py`, `nanobot/crm/real_adapter.py`, and related direct-route tests are superseded-reference material, not the production route.
- Future implementation must not expand `RealCRMAdapter` unless the user explicitly reopens the direct Nanobot GraphQL route.

## Last Updated

2026-05-09
