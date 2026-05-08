# CRM MCP Server

This package is a skeleton for a future read-only CRM MCP Server.

Current status:

- Defines static server metadata.
- Defines the v1 read-only tool names.
- Keeps real CRM access disabled by default.
- Does not implement GraphQL transport.
- Does not read `.env.nanobot`.
- Does not require an endpoint, token, secret, or endpoint auth header to import or create the skeleton.
- Does not connect to Nanobot configuration.
- Does not connect to DingTalk.

Current mocked tools:

- `crm_smoke_check` for sanitized diagnostics.
- `crm_list_projects` for mocked read-only project listing.

Configuration guidance lives in `docs/crm/MCP_CONFIGURATION.md`.

Future stdio and HTTP examples are documentation-only until Nanobot mock-mode wiring verifies the actual entrypoint. Do not assume `python -m crm_mcp_server` is a working MCP process yet.

15G does not require CRM credentials. 15H mock mode must not require CRM credentials. Optional real smoke is deferred to 15I and requires explicit user approval with runtime configuration outside chat.

15I optional real smoke command:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke
```

The command prints sanitized diagnostics only: status, read-only flags, operation names, count fields, reason, and sanitized error categories.
