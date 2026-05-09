# CRM MCP Server Design

This document describes the design for a separate read-first CRM MCP Server with one confirmation-gated `createReport` path. It does not define implementation code or arbitrary CRM writeback.

## Purpose

The CRM MCP Server is the real CRM access layer for CRM opportunity intelligence.

It isolates CRM GraphQL transport, credentials, allow-listing, pagination, redaction, and normalized source references outside Nanobot. Nanobot should consume approved MCP tools rather than direct CRM GraphQL clients.

## Goals

- Expose v1 report-assistant stdio tools for sales daily/weekly and presales weekly workflows, plus the single confirmation-gated `createReport` path.
- Keep CRM credentials and auth headers out of Nanobot runtime, `.dek`, docs, tests, logs, fixtures, and memory.
- Enforce the GraphQL query allow-list in `GRAPHQL_CONTRACT.md`.
- Reject all mutations before transport execution except explicitly confirmed `createReport`.
- Return sanitized, normalized data or report-ready facts with evidence references.
- Support local development with mocked GraphQL transport and synthetic data.
- Support future manual smoke checks only through explicit operator approval and runtime configuration.

## Non-Goals

- No unconfirmed CRM writeback.
- No CRM mutation except confirmation-gated `createReport` in v1.
- No CRM task creation.
- No customer contact, assignment, messaging, approval, audit, review, sync, export, or mutation workflow.
- No DingTalk-specific behavior in the MCP server.
- No Nanobot built-in native CRM tool registration.
- No storage of raw CRM payloads, generated production reports, or real CRM business data.
- No new CRM master data system or BI dashboard.

## Boundary

```text
Nanobot
  mock/report/metrics/evidence
  MCP client configuration
        |
        | approved CRM MCP read tools + confirmed createReport path
        v
CRM MCP Server
  tool contracts
  request validation
  GraphQL allow-list
  pagination and normalization
  redaction and sanitized errors
        |
        | read queries + confirmed createReport only
        v
CRM GraphQL source
```

Nanobot remains responsible for mock CLI verification, deterministic local report generation, and evidence display. The MCP server is responsible for real CRM reads and conversion into safe tool results.

## Components

| Component | Responsibility |
| --- | --- |
| MCP tool layer | Defines approved tool names, input schemas, output schemas, read-tool semantics, and the single confirmation-gated report write tool. |
| Request validator | Validates report type, date/window, scope, pagination limits, and requested source types before CRM access. |
| GraphQL allow-list | Maps read tools to allowed GraphQL `Query` operations and maps only `crm_create_report_after_confirmation` to confirmation-gated `createReport`. |
| GraphQL transport | Executes runtime-configured CRM GraphQL requests. Implementation must keep auth material out of logs and errors. |
| Pagination controller | Applies safe page size and max-page limits. Stops on empty pages or configured caps. |
| Normalizer | Converts allow-listed GraphQL objects into sanitized normalized records and source references. |
| Redaction layer | Removes credentials, auth headers, raw payloads, contact details, and unsupported free text from outputs/errors. |
| Error mapper | Converts config, validation, CRM unavailable, authorization, GraphQL, pagination, normalization, and empty-data failures into stable sanitized categories. |
| Test harness | Uses mocked transport and synthetic GraphQL responses only. |

## Data Flow

MCP invocation flow:

```text
CLI/DingTalk user request
  -> Nanobot agent
  -> CRM MCP tool
  -> crm_mcp_server
  -> CRM GraphQL
  -> normalized CRM result
  -> Nanobot draft/table or confirmed write result
```

1. Nanobot calls an approved MCP tool with report type, date/window, scope, and optional limits.
2. The MCP server validates the input and rejects invalid requests before CRM access.
3. Read tools map the request to a fixed set of allow-listed GraphQL `Query` operations.
4. `crm_create_report_after_confirmation` may map only to `createReport` after explicit confirmation; all other mutation paths are rejected.
5. The GraphQL transport executes the allow-listed request using runtime configuration.
6. Pagination applies conservative page size and maximum page limits for read paths.
7. Normalization converts GraphQL objects to sanitized records and source references.
8. Deterministic aggregation may run in the MCP server only if the tool contract says it returns metrics or report-ready facts.
9. The response returns sanitized records, metrics, unavailable markers, source references, and error categories as applicable.
10. Nanobot uses the returned facts with its existing mock/report/metrics/evidence path or displays/report-builds from the MCP output.

## Tool Granularity

V1 should prefer report-oriented read tools over raw GraphQL-shaped tools.

Rationale:

- Smaller public surface for Nanobot.
- Easier allow-listing.
- Lower chance of exposing raw payloads.
- Better alignment with deterministic metric and evidence trace requirements.

The first tool contract is defined in `MCP_TOOL_CONTRACT.md`.

## Error Handling

Errors must be stable and sanitized.

Recommended categories:

- `invalid_request`
- `config_missing`
- `crm_unavailable`
- `unauthorized_or_forbidden`
- `graphql_error`
- `pagination_limit_reached`
- `normalization_failed`
- `missing_required_fields`
- `empty_result`
- `rate_limited`
- `internal_error`

Error responses must not include credentials, endpoint auth headers, raw GraphQL payloads, customer details, contact details, or full request variables.

## Security Requirements

- MCP server is disabled or inert unless runtime config explicitly enables real CRM access.
- Credentials and auth headers are runtime-only and never documented as concrete values.
- All GraphQL operations must be allow-listed by operation name and operation type.
- Mutations are rejected before transport execution except confirmation-gated `createReport`.
- Raw CRM payloads are never returned to Nanobot.
- Logs and errors use sanitized categories and correlation ids only.
- Tests use synthetic data and mocked transport.
- Optional real smoke tests require explicit operator approval and runtime configuration outside chat.

## Deployment Notes

The MCP server may be deployed as:

- Stdio MCP process launched by Nanobot configuration.
- Separate internal HTTP MCP endpoint.
- Separate service in a future Docker Compose profile.

The exact deployment mode is not selected by this design. The tool contract should remain stable across deployment modes.

Detailed future stdio, HTTP, Docker, Compose, token-handling, and verification examples live in `MCP_CONFIGURATION.md`.

Current mock stdio status:

- The CRM MCP Server starts as a mock-mode stdio MCP process with `python -m crm_mcp_server`.
- Live stdio metadata publishes only the seven CRM Report Assistant tools.
- Legacy smoke/list helpers remain helper/test-only paths and are not live stdio tools.
- Mock mode does not implement a real CRM HTTP transport or real CRM writes.
- Mock mode does not connect DingTalk or enable real CRM smoke.

Future containerization should keep the CRM MCP Server image separate from the Nanobot image. Runtime credentials must not be baked into images or written into Compose files. If Compose syntax must be checked around secret-bearing configuration, prefer `docker compose config --quiet` and do not record expanded config output.

## Open Questions

1. Should v1 MCP tools return normalized records, report-ready metrics, or both?
2. Which runtime deployment mode is preferred: stdio, HTTP, or separate internal service?
3. Which CRM owner and date fields are authoritative for v1 reports?
4. Which amount field shape is canonical for deterministic metrics?
5. Which free-text fields are allowed after redaction, if any?
