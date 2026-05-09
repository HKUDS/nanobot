# CRM Documentation

This directory is the canonical entry point for CRM opportunity intelligence documentation. Canonical CRM docs live under `docs/crm/`.

## Current Direction

The selected production direction is a separate read-first CRM MCP Server with one confirmation-gated report write path. The CRM MCP Server is the current real CRM access direction.

Nanobot keeps the local mock/reporting layer:

- Synthetic/mock CRM data for development verification.
- Deterministic metrics for counts, amounts, distributions, date windows, and status labels.
- Report builders for daily, weekly, and dashboard summaries.
- Report-local evidence traces for key business conclusions.
- Mock CLI and Docker smoke paths that do not require real CRM access.

Real CRM GraphQL access moves out of Nanobot and into the CRM MCP Server:

- The MCP server owns CRM credentials and GraphQL transport.
- Nanobot connects to the MCP server through existing MCP configuration.
- Nanobot should not register a native built-in CRM tool for real CRM access.
- Nanobot should not read CRM GraphQL credentials, auth headers, or raw CRM payloads.

DingTalk remains deferred. Existing DingTalk channel documentation remains useful later, but this phase does not add CRM-specific DingTalk behavior.

Arbitrary writeback remains out of scope. V1 must not update, delete, assign, contact, message, task, export, or otherwise mutate CRM state, and the only allowed create path is confirmation-gated `createReport` through the approved MCP tool.

## Canonical Docs

| Document | Purpose |
| --- | --- |
| `GRAPHQL_CONTRACT.md` | Read-first GraphQL source contract plus confirmation-gated `createReport` path used by the future CRM MCP Server. |
| `MCP_SERVER_DESIGN.md` | Design for the separate read-first CRM MCP Server with one confirmation-gated report write path. No implementation details. |
| `MCP_TOOL_CONTRACT.md` | V1 MCP tool names, inputs, outputs, and safety boundaries. |
| `MCP_CONFIGURATION.md` | Future Docker, stdio MCP, HTTP MCP, token-handling, and safe verification guidance. |
| `examples/nanobot-crm-mcp.mock.yaml` | 15H mock-mode Nanobot MCP config example parsed by the real Nanobot config schema. |
| `MANUAL_TEST.md` | Safe manual checks for mock CLI, Docker smoke, and future MCP smoke. |
| `MIGRATION_NOTES.md` | Migration rationale from in-process `RealCRMAdapter` to CRM MCP Server. |
| `DOCS_INVENTORY.md` | Inventory and classification of CRM-related docs and task artifacts. |
| `REAL_ADAPTER_CLEANUP_REVIEW.md` | 15J cleanup review and Option B decision record for the superseded direct GraphQL route. |

## Current MCP Server Status

- The CRM MCP Server package is evolving toward the CRM Report Assistant MCP package.
- The current config example starts the mock-mode stdio MCP server with `python -m crm_mcp_server`; `python -m crm_mcp_server --metadata` remains available for safe metadata inspection.
- Current report-assistant metadata tools are `crm_collect_sales_daily_context`, `crm_collect_sales_weekly_context`, `crm_collect_presales_weekly_context`, `crm_generate_sales_daily_draft`, `crm_generate_sales_weekly_draft`, `crm_generate_presales_weekly_table`, and `crm_create_report_after_confirmation`.
- The package includes injected-transport read helpers and a confirmation-gated `createReport` helper for tests/library use, not a production MCP stdio write server.
- V1 report writes accept exactly two confirmation phrases: `确认提交这份日报` for daily reports and `确认提交这份周报` for weekly reports.
- The mock-mode stdio example does not require CRM credentials and does not configure a real CRM endpoint, token, headers, or real CRM writeback.
- Optional real smoke is deferred to 15I and requires explicit user approval with runtime configuration outside chat.

## Superseded Docs

`docs/crm-graphql-contract.md` is superseded by canonical `docs/crm/GRAPHQL_CONTRACT.md` and kept temporarily for migration review only. Do not use it as the source of truth for new implementation work.

## Safety Rules

- Do not write real CRM business data, customer data, generated production reports, tokens, secrets, auth headers, or raw CRM payloads into docs, `.dek`, fixtures, logs, or memory.
- Do not read local `.env*` files for documentation work.
- Do not access real CRM during documentation work.
- Use synthetic/mock data for local verification.
- Keep `.dek` as development governance only, never production runtime input or report storage.
