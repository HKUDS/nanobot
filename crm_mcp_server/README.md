# CRM MCP Server

This package is evolving toward the CRM Report Assistant MCP package. V1 remains read-first and includes one confirmation-gated report write path for `createReport`.

Current status:

- Defines static server metadata.
- Defines the v1 read-first tool names for collecting report context, generating drafts/tables, and confirmation-gated report creation.
- Keeps live stdio MCP tools mocked/read-only by default, except for the confirmation-gated report creation tool.
- Includes a confirmation-gated report write plan/implementation for `crm_create_report_after_confirmation`; it must not call `createReport` without a matching confirmation phrase and confirmation package.
- Includes an optional sanitized real-smoke GraphQL transport for explicitly approved local diagnostics.
- Does not read `.env.nanobot`.
- Does not require an endpoint, token, secret, or endpoint auth header to import or create the skeleton.
- Does not connect to Nanobot configuration.
- Does not connect to DingTalk.

Live stdio tools:

- `crm_collect_sales_daily_context`, `crm_collect_sales_weekly_context`, and `crm_collect_presales_weekly_context` for report-assistant context collection.
- `crm_generate_sales_daily_draft`, `crm_generate_sales_weekly_draft`, and `crm_generate_presales_weekly_table` for draft/table generation.
- `crm_create_report_after_confirmation` for confirmation-gated report creation.

Legacy/helper-only code paths not exposed by the live stdio tool contract:

- `crm_smoke_check` for sanitized diagnostics.
- `crm_list_projects` for mocked/injected-transport project listing.
- `crm_list_business_chances` for mocked/injected-transport business chance listing.

Configuration guidance lives in `docs/crm/MCP_CONFIGURATION.md`.

Mock stdio usage:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server
uv run --project crm_mcp_server python -m crm_mcp_server --metadata
```

The checked-in Nanobot example starts the mock-mode stdio MCP server with `python -m crm_mcp_server`. This stdio path is mock-mode only: it does not connect to real CRM, does not configure real CRM endpoint/token/header values, does not connect to DingTalk, and does not perform real CRM writes. Use `python -m crm_mcp_server --metadata` for safe metadata inspection without starting stdio serving.

15G does not require CRM credentials. 15H mock mode must not require CRM credentials. Optional real smoke is part of 15I and requires explicit user approval with runtime configuration outside chat.

15I optional real smoke command:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke
```

The command prints sanitized diagnostics only: status, read-only flags, operation names, count fields, reason, and sanitized error categories. Its default CRM GraphQL auth mode is `bearer`; `--auth-mode private_token` and `--auth-mode cookie` are retained only for explicit diagnostic comparison.

`crm_list_projects` and `crm_list_business_chances` stay mocked/injected-transport only by default. Library callers must pass `runtime_enabled=true` and provide complete runtime configuration before either tool can construct the bearer real transport. Tool outputs remain sanitized and must not include endpoint values, tokens, raw GraphQL payloads, contact details, amount-like values, or large raw free-text dumps. Generated internal reports may include useful business names and concise summaries needed for daily/weekly report drafting.
