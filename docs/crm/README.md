# CRM Documentation

This directory is the canonical entry point for CRM opportunity intelligence documentation. Canonical CRM docs live under `docs/crm/`.

## Current Direction

The selected production direction is a separate read-only CRM MCP Server. The CRM MCP Server is the current real CRM access direction.

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

Writeback remains out of scope. V1 must not create, update, delete, assign, contact, message, task, export, or otherwise mutate CRM state.

## Canonical Docs

| Document | Purpose |
| --- | --- |
| `GRAPHQL_CONTRACT.md` | Read-only GraphQL source contract used by the future CRM MCP Server. |
| `MCP_SERVER_DESIGN.md` | Design for the separate read-only CRM MCP Server. No implementation details. |
| `MCP_TOOL_CONTRACT.md` | V1 MCP tool names, inputs, outputs, and safety boundaries. |
| `MCP_CONFIGURATION.md` | Future Docker, stdio MCP, HTTP MCP, token-handling, and safe verification guidance. |
| `examples/nanobot-crm-mcp.mock.yaml` | 15H mock-mode Nanobot MCP config example parsed by the real Nanobot config schema. |
| `MANUAL_TEST.md` | Safe manual checks for mock CLI, Docker smoke, and future MCP smoke. |
| `MIGRATION_NOTES.md` | Migration rationale from in-process `RealCRMAdapter` to CRM MCP Server. |
| `DOCS_INVENTORY.md` | Inventory and classification of CRM-related docs and task artifacts. |
| `REAL_ADAPTER_CLEANUP_REVIEW.md` | 15J cleanup review and Option B decision record for the superseded direct GraphQL route. |

## Current MCP Server Status

- The CRM MCP Server is currently mock/read-only/sanitized.
- 15H adds a mock-mode Nanobot MCP config example and schema parse test; it does not enable real CRM access.
- `crm_smoke_check` is the diagnostics tool.
- `crm_list_projects` is the mocked read tool.
- The mock-mode example enables only `crm_smoke_check` and `crm_list_projects` and does not require CRM credentials.
- Optional real smoke is deferred to 15I and requires explicit user approval with runtime configuration outside chat.

## Superseded Docs

`docs/crm-graphql-contract.md` is superseded by canonical `docs/crm/GRAPHQL_CONTRACT.md` and kept temporarily for migration review only. Do not use it as the source of truth for new implementation work.

## Safety Rules

- Do not write real CRM business data, customer data, generated production reports, tokens, secrets, auth headers, or raw CRM payloads into docs, `.dek`, fixtures, logs, or memory.
- Do not read local `.env*` files for documentation work.
- Do not access real CRM during documentation work.
- Use synthetic/mock data for local verification.
- Keep `.dek` as development governance only, never production runtime input or report storage.
