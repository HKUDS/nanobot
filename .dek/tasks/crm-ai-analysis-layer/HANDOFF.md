# Handoff

Task id: `crm-ai-analysis-layer`

## Summary

This task prepares a first-version CRM AI analysis layer on top of Nanobot Docker delivery. CRM mock-mode implementation and Docker smoke are complete. Task 14A extracted the GraphQL read contract from `/Users/yang/Desktop/CRM_schema.md`. Task 14B extended normalized model dataclasses for GraphQL-backed CRM records. Task 14C added a fail-closed GraphQL client shell with injected mocked transport. Task 14D implemented `RealCRMAdapter` against mocked GraphQL responses only. No real CRM endpoint was accessed, no `.env.nanobot` content was read, no secrets were requested or copied, and no real HTTP transport was implemented.

Current direction has changed: do not continue the real CRM path as an in-process Nanobot `RealCRMAdapter` that talks directly to GraphQL. The selected direction is a separate read-only CRM MCP Server as the real CRM access layer. Canonical CRM documentation now lives under `docs/crm/`.

`.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` and `TASKS.md` have been updated to MCP-first route. No business code or MCP server implementation was added in that update.

Task 15B then created an independent `crm_mcp_server/` package skeleton. Task 15C added the static read-only GraphQL operation contract for that package: canonical v1 Query allow-list, fixed selection-set construction, forbidden Mutation checks, write-like operation-name rejection, no raw GraphQL passthrough, and no network transport. Task 15D added `crm_smoke_check` as a mocked-transport, read-only diagnostic tool that returns sanitized boundary/status/count fields only. Task 15E added `crm_list_projects` as the first mocked GraphQL data tool, returning sanitized minimal project records and source refs. Task 15F hardened redaction and diagnostics with shared safe error helpers, uniform ToolError shape, diagnostics allow-lists, cross-tool sensitive marker tests, and source safety assertions. Task 15G added future-only Docker, stdio MCP, HTTP MCP, token-handling, enabled-tool, forbidden-tool, and safe verification docs. Task 15H added a checked-in mock-mode Nanobot MCP config example parsed by the real Nanobot `Config` schema. Task 15I added an optional MCP real-smoke module, but the package-local smoke result was sanitized `INCONCLUSIVE/config_missing`, with no real CRM request made. Task 15J phase one added cleanup review/inventory only in `docs/crm/REAL_ADAPTER_CLEANUP_REVIEW.md`. Option B was then selected and applied by archiving `docs/crm-graphql-contract.md` in place with a strong superseded-reference header. Task 15K executed approved Option B cleanup by strengthening superseded-reference docs and adding reference-only module docstrings to the old direct GraphQL code. Task 16A added `crm_list_business_chances` as the second mocked GraphQL data tool, returning sanitized minimal business chance records and source refs. No real CRM access, `.env*` reads, DingTalk work, Mutation, writeback, raw GraphQL passthrough, or runtime Nanobot wiring was added.

## Files

- `.dek/tasks/crm-ai-analysis-layer/FACTS.md`
- `.dek/tasks/crm-ai-analysis-layer/PLAN.md`
- `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md`
- `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md`
- `docs/crm/README.md`
- `docs/crm/GRAPHQL_CONTRACT.md`
- `docs/crm/MCP_SERVER_DESIGN.md`
- `docs/crm/MCP_TOOL_CONTRACT.md`
- `docs/crm/MCP_CONFIGURATION.md`
- `docs/crm/examples/nanobot-crm-mcp.mock.yaml`
- `docs/crm/MANUAL_TEST.md`
- `docs/crm/MIGRATION_NOTES.md`
- `docs/crm/DOCS_INVENTORY.md`
- `docs/crm/REAL_ADAPTER_CLEANUP_REVIEW.md`
- `docs/crm-graphql-contract.md`
- `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md`
- `.dek/changes/crm-opportunity-intelligence/TASKS.md`
- `crm_mcp_server/pyproject.toml`
- `crm_mcp_server/README.md`
- `crm_mcp_server/crm_mcp_server/__init__.py`
- `crm_mcp_server/crm_mcp_server/contract.py`
- `crm_mcp_server/crm_mcp_server/graphql.py`
- `crm_mcp_server/crm_mcp_server/diagnostics.py`
- `crm_mcp_server/crm_mcp_server/business_chances.py`
- `crm_mcp_server/crm_mcp_server/projects.py`
- `crm_mcp_server/crm_mcp_server/redaction.py`
- `crm_mcp_server/crm_mcp_server/schemas.py`
- `crm_mcp_server/crm_mcp_server/server.py`
- `crm_mcp_server/tests/conftest.py`
- `crm_mcp_server/tests/test_server_skeleton.py`
- `crm_mcp_server/tests/test_forbidden_tools.py`
- `crm_mcp_server/tests/test_read_contract.py`
- `crm_mcp_server/tests/test_forbidden_mutation.py`
- `crm_mcp_server/tests/test_smoke_check.py`
- `crm_mcp_server/tests/test_list_projects.py`
- `crm_mcp_server/tests/test_list_business_chances.py`
- `crm_mcp_server/tests/test_redaction.py`
- `crm_mcp_server/tests/test_real_smoke.py`
- `nanobot/crm/models.py`
- `tests/crm/test_models.py`
- `nanobot/crm/graphql_client.py`
- `tests/crm/test_graphql_client.py`
- `nanobot/crm/adapters.py`
- `nanobot/crm/real_adapter.py`
- `tests/crm/test_adapters.py`
- `tests/crm/test_real_adapter_contract.py`
- `tests/crm/test_real_adapter_redaction.py`

## Key Findings

- Nanobot already has Docker and Docker Compose delivery.
- CLI entry exists through the `nanobot` Typer app.
- DingTalk is already a built-in channel.
- Extension mechanisms exist for skills, tools, channels, providers, memory, cron/heartbeat, and MCP.
- MCP is a strong candidate for isolating read-only CRM access and allow-listing exposed CRM operations.
- Memory/Dream behavior must be constrained so CRM data and generated reports do not become long-term memory by default.
- The CRM GraphQL endpoint documented by the schema is `http://api.in.chaitin.net/crm/query`.
- The v1 GraphQL read allow-list is `listReport`, `reportInfo`, `reportRelatedInfo`, `listProject`, `projectInfo`, `listActivity`, `listCompany`, `companyInfo`, `listUser`, `list_business_chance`, and `business_chance`.
- The schema includes a `Mutation` root and many write-like mutation fields, so v1 must reject all mutations before transport execution.
- `docs/crm-graphql-contract.md` now defines query allow-listing, forbidden mutation policy, normalization mapping, `SearchParam` to `ReportRequest` mapping, connection pagination, source references, redaction, runtime env vars, and open questions.
- `docs/crm/README.md` is the canonical CRM docs entry point and states the CRM MCP Server direction, retained Nanobot mock/report/metrics/evidence scope, deferred DingTalk scope, and CRM writeback exclusion.
- `docs/crm/GRAPHQL_CONTRACT.md` supersedes `docs/crm-graphql-contract.md` as the canonical read-only GraphQL source contract for the future CRM MCP Server.
- `docs/crm/MCP_SERVER_DESIGN.md` defines the design-only MCP server boundary, components, data flow, error handling, security requirements, and deployment options.
- `docs/crm/MCP_TOOL_CONTRACT.md` defines v1 read-only MCP report-facts tools, shared schemas, read-boundary diagnostics, forbidden write-like tool names, and sanitized error categories.
- `docs/crm/MANUAL_TEST.md` records safe mock CLI, Docker smoke, and future MCP smoke checks.
- `docs/crm/MIGRATION_NOTES.md` records why the direction moved from in-process `RealCRMAdapter` to CRM MCP Server, what code is retained, what plan work is superseded, and deletion gates for old docs/code.
- `docs/crm/DOCS_INVENTORY.md` classifies CRM-related docs and task files for MCP-route convergence.
- `docs/crm/REAL_ADAPTER_CLEANUP_REVIEW.md` is the 15J phase-one cleanup decision document. It classifies direct GraphQL / `RealCRMAdapter` route artifacts and recommends Option B for the current stage.
- `docs/crm-graphql-contract.md` is now superseded by `docs/crm/GRAPHQL_CONTRACT.md` and archived in place as historical migration reference.
- Task 15K executed approved Option B cleanup: `docs/crm-graphql-contract.md` is migration-review only, `docs/crm/GRAPHQL_CONTRACT.md` is canonical, and the old direct Nanobot GraphQL route is not the production path.
- `nanobot/crm/graphql_client.py` and `nanobot/crm/real_adapter.py` have reference-only module docstrings and are retained as superseded reference material.
- Related direct-route tests are retained as reference/safety material for normalization and redaction ideas, not targets for production CRM access expansion.
- `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` now states real CRM GraphQL access is owned by an independent CRM MCP Server, Nanobot keeps mock/report/metrics/evidence and mock CLI, `MCPCRMAdapter` or direct MCP tool usage is the future Nanobot connection layer, DingTalk is deferred, CRM writeback is out of scope, and real smoke must go through `crm_smoke_check` or an equivalent MCP tool.
- `.dek/changes/crm-opportunity-intelligence/TASKS.md` now preserves old task history but marks the direct in-process GraphQL client/`RealCRMAdapter` path as superseded for production.
- Future task sequence is 15A Design CRM MCP server, 15B Create MCP server skeleton with no real CRM access, 15C Implement read-only contract and forbidden mutation tests, 15D Implement `crm_smoke_check` with mocked transport, 15E Implement `crm_list_projects` with mocked GraphQL responses, 15F Implement redaction and diagnostics tests, 15G Add Docker/stdio/HTTP MCP configuration docs, 15H Wire Nanobot config to CRM MCP server in mock mode, 15I Optional real MCP smoke with user-provided env outside chat, and 15J Cleanup superseded RealCRMAdapter docs/code after user approval.
- Task 15B added `crm_mcp_server/` as an independent package skeleton with server metadata, runtime defaults disabling real CRM access, v1 read-only tool names, and tests proving no write-like tool names are exposed.
- 15B verification passed: `uv run --extra dev pytest crm_mcp_server/tests` reported `6 passed`, `uv run --extra dev ruff check crm_mcp_server` reported `All checks passed!`, and the independent package import check printed `crm-mcp-server`.
- 15B did not read `.env.nanobot`, access real CRM, implement GraphQL transport, add tokens/secrets/auth headers, add raw GraphQL payloads, implement Mutation, wire Nanobot config, connect DingTalk, or change Nanobot runtime core.
- Task 15C added `crm_mcp_server/crm_mcp_server/graphql.py` with `ReadOperation`, `GraphQLContractError`, fixed selection-set operation construction, and non-transport validation for mutation text.
- Task 15C added `V1_ALLOWED_QUERY_NAMES` and `list_v1_query_names()` to `crm_mcp_server/crm_mcp_server/contract.py`; the allow-list matches `docs/crm/GRAPHQL_CONTRACT.md`.
- Task 15C tests cover allow-listed Query construction, unknown operation rejection, operation type `mutation` rejection, query text containing `mutation` rejection, write-like operation-name rejection, absence of raw `run_graphql` / `execute_query` passthrough, sensitive contact-field omission from fixed selection sets, and no network access during operation construction.
- 15C verification passed: `uv run --extra dev pytest crm_mcp_server/tests` reported `15 passed in 0.02s`; `uv run --extra dev ruff check crm_mcp_server/crm_mcp_server/contract.py crm_mcp_server/crm_mcp_server/graphql.py crm_mcp_server/tests/test_read_contract.py crm_mcp_server/tests/test_forbidden_mutation.py` reported `All checks passed!`; the source safety assertion reported `15C safety assertions passed`.
- 15C did not read `.env.nanobot`, access real CRM, implement HTTP transport, add tokens/secrets/auth headers, expose raw GraphQL passthrough, implement Mutation, wire Nanobot config, connect DingTalk, or change Nanobot runtime core.
- Task 15D added `crm_smoke_check` to `V1_READ_ONLY_TOOL_NAMES` and server metadata.
- Task 15D added `crm_mcp_server/crm_mcp_server/diagnostics.py` with `MockGraphQLTransport` and sanitized `crm_smoke_check` diagnostics.
- Task 15D updated `docs/crm/MCP_TOOL_CONTRACT.md` to document `crm_smoke_check`, its allowed output fields, and forbidden output categories.
- Task 15D tests cover default disabled/config-missing output, mocked empty-result output, mocked one-record count output, GraphQL error sanitization, unauthorized sanitization, `mutation_used=false`, and absence of endpoint/token/Authorization/raw payload/customer/project/amount/contact/phone/email/free-text markers from output.
- 15D verification passed: `uv run --extra dev pytest crm_mcp_server/tests` reported `22 passed in 0.02s`; `uv run --extra dev ruff check crm_mcp_server/crm_mcp_server/contract.py crm_mcp_server/crm_mcp_server/server.py crm_mcp_server/crm_mcp_server/diagnostics.py crm_mcp_server/tests/test_smoke_check.py crm_mcp_server/tests/test_forbidden_tools.py docs/crm/MCP_TOOL_CONTRACT.md` reported `All checks passed!`; the source/output safety assertion reported `15D safety assertions passed`.
- 15D did not read `.env.nanobot`, access real CRM, implement real HTTP transport, add tokens/secrets/auth headers, output raw GraphQL payloads, implement Mutation, wire Nanobot config, connect DingTalk, or change Nanobot runtime core.
- Task 15E added `crm_list_projects` to `V1_READ_ONLY_TOOL_NAMES` and server metadata.
- Task 15E added `crm_mcp_server/crm_mcp_server/projects.py` with validation-before-transport, fixed `listProject` operation construction, pagination using `search.skip`/`search.limit`, default page size `50`, `MAX_RECORDS_CAP=200`, `MAX_PAGES=5`, sanitized record normalization, source refs, diagnostics, and sanitized error categories.
- Task 16A added `crm_mcp_server/crm_mcp_server/business_chances.py` with validation-before-transport, fixed `list_business_chance` operation construction, pagination using `search.skip`/`search.limit`, default page size `50`, `MAX_RECORDS_CAP=200`, `MAX_PAGES=5`, sanitized business chance record normalization, source refs, diagnostics, and sanitized error categories.
- Task 15E updated `docs/crm/MCP_TOOL_CONTRACT.md` to document `crm_list_projects`, its input, output, allowed record fields, diagnostics fields, and forbidden output categories.
- Task 15E tests cover read-only tool exposure, mocked `listProject` normalization, validation before transport, pagination variables, max records/pages safety, source refs, sensitive marker exclusion, GraphQL error sanitization, empty result diagnostics, `mutation_used=false`, and write-like tool names remaining hidden.
- 15E verification passed: `uv run --extra dev pytest crm_mcp_server/tests` reported `35 passed in 0.03s`; `uv run --extra dev ruff check crm_mcp_server` reported `All checks passed!`; the source/output safety assertion reported `15E safety assertions passed`.
- 15E did not read `.env.nanobot` or any `.env*`, access real CRM, implement real HTTP transport, request or output tokens, output raw GraphQL payloads, expose project/customer names, amount, contact details, implement Mutation, expose raw GraphQL passthrough, wire Nanobot MCP config, connect DingTalk, or change Nanobot runtime core.
- Task 15F added `crm_mcp_server/crm_mcp_server/redaction.py` with `sanitize_error` and `sanitize_errors` safe helpers.
- Task 15F updated `crm_smoke_check` and `crm_list_projects` to return uniform ToolError objects with `category`, fixed safe `message`, and `retryable`.
- Task 15F tightened `crm_list_projects` diagnostics to include `mutations_allowed`, `graphql_errors_count`, and `pagination_limit_reached`, and to reject missing source ids with sanitized `missing_required_fields`.
- Task 15F updated `docs/crm/MCP_TOOL_CONTRACT.md` to document fixed safe error messages, diagnostics allow-listed fields, and forbidden output categories.
- Task 15F tests cover `sanitize_error` raw-message redaction, auth material redaction, unknown-category fallback, cross-tool sensitive marker exclusion, diagnostics field allow-lists, uniform ToolError shape, write-like tool-name exclusions, and runtime source checks for no network/env access.
- 15F verification passed: baseline `uv run --extra dev pytest crm_mcp_server/tests` reported `35 passed in 0.03s`; baseline `uv run --extra dev ruff check crm_mcp_server` reported `All checks passed!`; final `uv run --extra dev pytest crm_mcp_server/tests` reported `44 passed in 0.03s`; final `uv run --extra dev ruff check crm_mcp_server` reported `All checks passed!`; source safety assertion via `uv run python - <<'PY' ... PY` reported `15F source safety assertions passed`.
- The requested plain `python - <<'PY' ... PY` source safety command did not run because `python` is not on PATH in this shell; the same assertion passed via `uv run python`.
- 15F did not read `.env.nanobot` or any `.env*`, access real CRM, implement real HTTP transport, request or output tokens, output raw GraphQL payloads, expose project/customer names, amount, contact details, implement Mutation, expose raw GraphQL passthrough, wire Nanobot MCP config, connect DingTalk, or change Nanobot runtime core.
- Task 15G added `docs/crm/MCP_CONFIGURATION.md` and updated `docs/crm/README.md`, `docs/crm/MCP_SERVER_DESIGN.md`, `docs/crm/MANUAL_TEST.md`, `docs/crm/DOCS_INVENTORY.md`, and `crm_mcp_server/README.md`.
- 15G documents that the CRM MCP Server remains mock/read-only/sanitized, `crm_smoke_check` is diagnostics-only, `crm_list_projects` is mocked read-only, 15G does not enable real CRM, and 15I is the first optional real-smoke task after explicit approval.
- 15G future stdio MCP example is mock-mode only and explicitly planned/future until 15H or later verifies a real `crm_mcp_server` entrypoint.
- 15G future HTTP MCP example uses `http://crm-mcp-server.internal:8080/mcp` as an MCP endpoint placeholder and states it is not the CRM GraphQL source endpoint.
- 15G Docker/Compose guidance states future CRM MCP Server containerization should be independent from the Nanobot image, must not bake `.env*` into images, must not write tokens into Compose files, and should use `docker compose config --quiet` for syntax checks when needed.
- 15G token handling states 15G and 15H mock mode do not need a token; 15I optional real smoke may need runtime values only after explicit approval; tokens must not be sent to chat or written into docs, `.dek`, tests, fixtures, git, logs, or memory.
- 15G currently allowed tools for future mock-mode examples are `crm_smoke_check` and `crm_list_projects`; raw GraphQL passthrough, Mutation, create/update/delete/assign/contact/message/export/writeback tools, and DingTalk write/send integration remain forbidden.
- 15G changed documentation only. It did not change runtime code, Nanobot runtime config, Dockerfile, `docker-compose.yml`, DingTalk files, the real CRM adapter path, or any actual MCP config.
- 15G did not access real CRM, did not read `.env.nanobot` or any `.env*`, did not request a token, and did not write real tokens, endpoint auth headers, raw GraphQL request/response, or real CRM data.
- 15G verification passed: `uv run --extra dev pytest crm_mcp_server/tests` reported `44 passed in 0.04s`; `uv run --extra dev ruff check crm_mcp_server` reported `All checks passed!`; requested plain `python - <<'PY' ... PY` docs safety command failed to start because `python` is not on PATH; the same assertion via `uv run python - <<'PY' ... PY` reported `15G docs safety assertions passed`.
- Task 15H added `docs/crm/examples/nanobot-crm-mcp.mock.yaml` with a stdio mock-mode CRM MCP server config, using `uv run --project crm_mcp_server python -m crm_mcp_server`, `toolTimeout: 30`, no env, no headers, and only `crm_smoke_check` / `crm_list_projects` enabled.
- 15H added `tests/config/test_crm_mcp_config.py`, which parses the example through `nanobot.config.schema.Config.model_validate`, asserts the enabled tools and timeout, checks no sensitive markers or real endpoint markers are present, and checks no write-like tool names are enabled.
- 15H confirmed `nanobot/config/schema.py` already supports `tools.mcpServers`, stdio `command`/`args`, HTTP-family `url`, `enabledTools`, and `toolTimeout`; no schema change was needed.
- 15H updated `docs/crm/MCP_CONFIGURATION.md`, `docs/crm/MANUAL_TEST.md`, and `docs/crm/README.md` for the mock-mode example and verification path.
- 15H did not access real CRM, read `.env.nanobot` or any `.env*`, request a token, write CRM credentials, add real endpoint config, implement HTTP transport, connect DingTalk, implement Mutation, expose raw GraphQL passthrough, or modify `Dockerfile`, `docker-compose.yml`, or `entrypoint.sh`.
- 15H verification passed: `uv run --extra dev pytest tests/config/test_crm_mcp_config.py` reported `3 passed in 0.21s`; `uv run --extra dev pytest crm_mcp_server/tests` reported `44 passed in 0.03s`; `uv run --extra dev ruff check tests/config/test_crm_mcp_config.py crm_mcp_server` reported `All checks passed!`; requested plain `python - <<'PY' ... PY` docs safety command failed to start because `python` is not on PATH; the same assertion via `uv run python - <<'PY' ... PY` reported `15H config docs safety assertions passed`.
- Task 15I added `crm_mcp_server/crm_mcp_server/real_smoke.py` with `RealSmokeConfig`, `RealGraphQLSmokeTransport`, `load_real_smoke_config_from_env()`, `run_real_crm_smoke()`, and a sanitized JSON module runner.
- Task 15I added `crm_mcp_server/tests/test_real_smoke.py` covering config-missing behavior, fake success count-only output, unauthorized sanitization, GraphQL error sanitization, repr redaction, fixed `listProject` limit-one operation shape, module stdout sanitization, and source safety.
- 15I uses only runtime environment values visible to the process; a credential pasted in chat was not used, stored, or copied into files. Consider that pasted credential compromised and rotate it outside this workflow.
- 15I requested root command `uv run --extra dev python -m crm_mcp_server.real_smoke` failed before module execution because the independent package is not on the root project module path. Package-local command `uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke` ran.
- 15I package-local real smoke returned sanitized status `INCONCLUSIVE`, reason `config_missing`, `data_count=0`, `normalized_count=0`, `graphql_errors_count=0`, `mutation_used=false`, `runtime_enabled=false`, error category `config_missing`. No real CRM request was made. No endpoint, token, raw GraphQL request/response, variables, customer/project/contact data, amount, address, or note was recorded.
- 15I final verification passed for the implemented smoke path: `uv run --extra dev pytest crm_mcp_server/tests/test_real_smoke.py` reported `8 passed in 0.02s`; `uv run --extra dev pytest crm_mcp_server/tests` reported `52 passed in 0.04s`; `uv run --extra dev ruff check crm_mcp_server` reported `All checks passed!`; source safety assertion via `uv run python - <<'PY' ... PY` reported `15I source safety assertions passed`; package-local smoke returned sanitized `INCONCLUSIVE/config_missing`.
- 15I did not change DingTalk files, Nanobot production runtime wiring, Docker Compose secret handling, the old in-process `RealCRMAdapter` path, or fixtures/snapshots with real data.
- 15J phase-one cleanup review and Option B cleanup did not delete, move, rename, or modify runtime business code. Option B only marked `docs/crm-graphql-contract.md` archived in place and updated cleanup docs/status. It did not rerun real smoke, access real CRM, read `.env*`, handle tokens, modify tests to skip the old route, clean DingTalk, or do writeback/Mutation work.
- `nanobot/crm/models.py` now defines `ActivityRecord`, `ReportRecord`, `CustomerRecord`, `BusinessChanceRecord`, and `SalesRepRecord`, and `OpportunityRecord` has optional owner/customer display fields for GraphQL `Project` mapping.
- 14B tests assert models can be constructed from synthetic GraphQL-like payloads, `CRMSourceRef` avoids token/secret markers, and models do not import transport/integration code.
- `nanobot/crm/graphql_client.py` now defines `CRMGraphQLClient`, `CRMGraphQLClientError`, `GraphQLTransport`, and the v1 default read allow-list.
- 14C tests assert allow-listed queries succeed through fake transport, unknown operations are rejected before transport, mutation strings are rejected even under allow-listed names, variables including pagination are forwarded, GraphQL/transport errors are sanitized, fake tokens do not appear in exception text, and the module does not import real HTTP/env-reading dependencies.
- `nanobot/crm/real_adapter.py` now defines `RealCRMAdapter` with read-only methods `read_opportunities`, `read_activities`, `read_reports`, `read_customers`, and `read_business_chances`.
- `CRMAdapter` protocol now includes the same read-only methods; writeback method fragments remain forbidden by tests.
- 14D tests use synthetic mocked GraphQL responses, verify normalized record outputs, pagination variables, missing-field errors, CRM unavailable and GraphQL error mapping, unauthorized redaction, and absence of raw payload/credential leaks.
- The internal GraphQL client/`RealCRMAdapter` continuation route is now superseded by the external CRM MCP Server direction. Keep the completed work as reference only unless the user explicitly reopens it.
- 15J review classification: keep canonical MCP docs, CRM MCP Server code, mock/report/metrics/evidence path, shared models, and `CRMAdapter` protocol; keep `nanobot/crm/graphql_client.py`, `nanobot/crm/real_adapter.py`, and direct-route tests as superseded-reference for now; keep `docs/crm-graphql-contract.md` archived in place; treat direct-route diagnostics code/tests as needs-user-decision for any future cleanup.
- Option B has been applied. Option C is still premature because 15I remains `INCONCLUSIVE/config_missing` and no real CRM request was made.
- 15K verification passed: `uv run --extra dev pytest crm_mcp_server/tests` reported `52 passed in 0.04s`; focused direct-route tests reported `20 passed in 0.24s`; `uv run --extra dev ruff check crm_mcp_server nanobot/crm/graphql_client.py nanobot/crm/real_adapter.py` reported `All checks passed!`; requested plain `python` safety assertion could not start because `python` is not on PATH, and the same assertion via `uv run python` reported `15K cleanup option B assertions passed`.
- 16A verification passed: focused `uv run --extra dev pytest crm_mcp_server/tests/test_list_business_chances.py` reported `14 passed in 0.02s`; full `uv run --extra dev pytest crm_mcp_server/tests` reported `66 passed`; `uv run --extra dev ruff check crm_mcp_server` reported `All checks passed!`.
- `docs/crm/GRAPHQL_CONTRACT.md` is canonical as the read-only GraphQL contract input for the future CRM MCP Server.
- DingTalk CRM delivery is deferred for now; do not add CRM-specific DingTalk behavior while the MCP read boundary is being planned.

## Next Step

16A is complete. Next choice: finish branch / commit / PR, implement another allow-listed mocked read tool, or start report-facts aggregation using `crm_list_projects` and `crm_list_business_chances` outputs. Wait for further explicit user approval before deeper cleanup such as moving/deleting direct adapter code/tests or handling `nanobot/crm/real_smoke_diagnostics.py`. If the user wants a real CRM smoke result before deeper cleanup, first fix runtime config propagation outside chat so the required package-local smoke runtime config is visible, then rerun only the sanitized 15I smoke after explicit approval. Do not output raw GraphQL requests/responses, customer/project data, token, endpoint auth headers, Authorization/Bearer/cookie material, amount, address, or contact/free-text CRM content.

## Questions To Resolve

1. Which auth mechanism should runtime GraphQL use?
2. Which project date field defines daily/weekly pipeline inclusion?
3. Which owner field is authoritative for sales scope?
4. What is the exact JSON shape of the `Money` scalar in real GraphQL responses?
5. Should `BusinessChance` merge into the opportunity stream or remain a separate source category?
6. Which free-text CRM fields are allowed in AI-readable summaries after redaction?
7. What page size and rate limits are safe for production CRM reads?
8. Should optional real CRM smoke tests run only behind explicit env flags and never in default CI?
9. What exact MCP tools should the CRM MCP Server expose for v1: report-level tools, raw read tools, or both?
10. Which Nanobot MCP configuration mode should be used for the CRM MCP Server: stdio, HTTP, or separately deployed internal endpoint?
