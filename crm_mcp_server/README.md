# CRM MCP Server

This package is a skeleton for a future read-only CRM MCP Server.

Current status:

- Defines static server metadata.
- Defines the v1 read-only tool names.
- Keeps normal MCP tools mocked/read-only by default.
- Includes an optional sanitized real-smoke GraphQL transport for explicitly approved local diagnostics.
- Does not read `.env.nanobot`.
- Does not require an endpoint, token, secret, or endpoint auth header to import or create the skeleton.
- Does not connect to Nanobot configuration.
- Does not connect to DingTalk.

Current mocked tools:

- `crm_smoke_check` for sanitized diagnostics.
- `crm_list_projects` for mocked read-only project listing.
- `crm_list_business_chances` for mocked read-only business chance listing.

Configuration guidance lives in `docs/crm/MCP_CONFIGURATION.md`.

Future stdio and HTTP examples are documentation-only until Nanobot mock-mode wiring verifies the actual entrypoint. Do not assume `python -m crm_mcp_server` is a working MCP process yet.

15G does not require CRM credentials. 15H mock mode must not require CRM credentials. Optional real smoke is part of 15I and requires explicit user approval with runtime configuration outside chat.

15I optional real smoke command:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke
```

The command prints sanitized diagnostics only: status, read-only flags, operation names, count fields, reason, and sanitized error categories. Its default CRM GraphQL auth mode is `bearer`; `--auth-mode private_token` and `--auth-mode cookie` are retained only for explicit diagnostic comparison.

`crm_list_projects` and `crm_list_business_chances` stay mocked/injected-transport only by default. Library callers must pass `runtime_enabled=true` and provide complete runtime configuration before either tool can construct the bearer real transport. Tool outputs remain sanitized and must not include endpoint values, tokens, raw GraphQL payloads, project/customer names, contact details, amount-like values, or free-text CRM notes.
