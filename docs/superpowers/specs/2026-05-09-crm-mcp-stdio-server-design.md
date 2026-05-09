# CRM MCP Stdio Server Design

## Goal

Implement a real stdio MCP server for the existing Python `crm_mcp_server` package so Nanobot can discover and call the CRM Report Assistant tools through its existing MCP client.

This phase turns `python -m crm_mcp_server` from metadata-only into a usable mock-mode MCP stdio process. It does not connect to real CRM, does not write real CRM data, and does not implement HTTP MCP serving.

## Current State

- Nanobot already has a Python MCP client wrapper in `nanobot/agent/tools/mcp.py` that supports stdio, SSE, streamable HTTP, tool discovery, tool calls, resources, prompts, timeouts, transient retry, and schema normalization.
- The CRM package currently exposes static metadata and report-assistant library helpers.
- `python -m crm_mcp_server --metadata` returns safe tool metadata.
- `python -m crm_mcp_server` currently does not start a working MCP stdio server.
- The checked-in Nanobot CRM MCP config is metadata-only and includes `--metadata`.

## Scope

In scope:

- Keep `--metadata` safe inspection mode.
- Add `python -m crm_mcp_server` stdio MCP serving.
- Register these report-assistant MCP tools:
  - `crm_collect_sales_daily_context`
  - `crm_collect_sales_weekly_context`
  - `crm_collect_presales_weekly_context`
  - `crm_generate_sales_daily_draft`
  - `crm_generate_sales_weekly_draft`
  - `crm_generate_presales_weekly_table`
  - `crm_create_report_after_confirmation`
- Back the tools with mock/injected readers and mock write transport only.
- Return JSON text content from tool calls so Nanobot's existing MCP wrapper can consume outputs without new client changes.
- Update the checked-in CRM MCP mock config to invoke the stdio server without `--metadata`.
- Add tests for tool registry behavior, metadata mode, stdio entrypoint wiring, and config expectations.

Out of scope:

- Real CRM GraphQL runtime readers.
- Real `createReport` writes.
- HTTP MCP server.
- DingTalk-specific behavior.
- Fixing the root `botocore` dependency download issue unless it blocks this phase's focused verification.
- Rust implementation.

## Architecture

Use a two-layer design.

### Tool Runtime Layer

Create a plain Python tool runtime module, for example `crm_mcp_server/tool_runtime.py`.

Responsibilities:

- Define a small `ToolDefinition` shape with `name`, `description`, `input_schema`, and handler.
- Expose `list_tool_definitions()` for registration.
- Expose `call_tool(name, arguments)` for direct unit tests and MCP adapter use.
- Keep handlers deterministic and mock-mode only.
- Serialize handler results as JSON-safe dictionaries.

Tool handlers call existing library helpers:

- Context tools call `collect_sales_daily_context`, `collect_sales_weekly_context`, or `collect_presales_weekly_context` with mock readers.
- Draft tools call `generate_sales_daily_draft`, `generate_sales_weekly_draft`, or `generate_presales_weekly_table` with supplied context or a generated mock context fallback.
- Write tool calls `prepare_create_report_confirmation` when no confirmation package is supplied, or `create_report_after_confirmation` with a mock transport when confirmation is supplied.

### MCP Stdio Adapter Layer

Create a thin MCP adapter module, for example `crm_mcp_server/stdio_server.py`.

Responsibilities:

- Register tool definitions with the Python MCP SDK.
- Convert MCP tool call arguments into `tool_runtime.call_tool()` calls.
- Return tool results as JSON text content.
- Avoid logging or returning raw exceptions, env values, endpoint values, headers, tokens, raw GraphQL, or transport internals.

`crm_mcp_server/__main__.py` should:

- Preserve `--metadata` behavior.
- Start the stdio server when no metadata flag is provided.
- Not require endpoint/token/env configuration.

## Tool Inputs

Use permissive but explicit JSON schemas for v1 mock-mode tools.

Context tools accept:

- `window`: object with optional `start` and `end` strings.
- `scope`: object with optional `scope_id`, `owner_ids`, and `group_ids`.
- `options`: object with optional `max_records` integer.

Draft tools accept:

- `context`: object. If missing, use a deterministic mock context.

Write tool accepts:

- `draft`: object for preparing confirmation package.
- `report_type`: `daily` or `weekly`.
- `target`: string.
- `to`: string array.
- `confirmation_package`: object, optional.
- `confirmation_text`: string, optional.

If `confirmation_package` or `confirmation_text` is missing, the write tool returns a confirmation package and does not call the mock transport.

If both are present, it runs the existing confirmation-gated write helper with mock transport.

## Data Flow

Mock context/draft flow:

```text
Nanobot MCP client
  -> python -m crm_mcp_server stdio process
  -> MCP tool call
  -> stdio adapter
  -> tool_runtime handler
  -> report_context/report_drafts helper
  -> JSON text result
```

Mock write flow:

```text
Nanobot MCP client
  -> crm_create_report_after_confirmation
  -> prepare confirmation package if not confirmed
  -> create_report_after_confirmation with mock transport if confirmed
  -> sanitized JSON text result
```

## Error Handling And Safety

- Unknown tool names return a sanitized error result.
- Invalid argument shapes return a sanitized error result, not raw exceptions.
- Tool outputs must not contain endpoint values, auth headers, tokens, cookies, raw GraphQL operation text, raw variables, raw responses, or raw error stacks.
- Mock write results may include sanitized report id, report type, target, mutation name, and status only.
- No tool attempts real network access in this phase.

## Configuration

Update `docs/crm/examples/nanobot-crm-mcp.mock.yaml` to remove `--metadata` from args.

The example remains mock-mode:

- `env` remains empty.
- `headers` remains empty.
- No endpoint/token references are added.
- Enabled tools remain the seven report-assistant tools.

Docs should say `--metadata` is still available for inspection, but the mock config now starts the stdio server.

## Testing Strategy

Unit tests:

- Tool runtime lists exactly the seven report-assistant tools for stdio registration.
- Each runtime handler returns JSON-safe, sanitized dictionaries.
- Write runtime does not call mock transport before confirmation.
- Confirmed write calls only the mock `createReport` path.

Entrypoint tests:

- `main(["--metadata"])` still prints safe metadata.
- Non-metadata `main()` dispatches to stdio server starter in tests without raising metadata-only errors.

MCP adapter tests:

- Tool definitions expose MCP-compatible input schemas.
- Tool call adapter returns JSON text content.

Config tests:

- Checked-in mock config no longer includes `--metadata`.
- Enabled tools match the report-assistant list.
- `env` and `headers` remain empty.

Verification commands:

```bash
uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests
uv run --project crm_mcp_server --with ruff ruff check crm_mcp_server tests/config/test_crm_mcp_config.py
uv run --project crm_mcp_server python -m crm_mcp_server --metadata
```

Root config test remains desirable:

```bash
uv run --with pytest --with pyyaml pytest tests/config/test_crm_mcp_config.py
```

If it is still blocked by `botocore` download before pytest starts, record it as an environment verification gap.

## Rust Decision

Do not implement this phase in Rust.

Rust is technically feasible, but it is not the right next step because:

- The existing CRM package, tests, report helpers, and Nanobot config are Python.
- The fastest useful milestone is stdio protocol wiring around existing Python functions.
- Rust would add crate layout, build, packaging, deployment, and Python/Rust boundary work before proving the tool contract.
- Current bottlenecks are protocol correctness, confirmation safety, and sanitization, not performance.

Rust can be reconsidered later if the CRM MCP server is split into a standalone service with stronger deployment/performance requirements.

## Acceptance Criteria

- `python -m crm_mcp_server --metadata` still returns safe metadata.
- `python -m crm_mcp_server` starts a stdio MCP server in tests instead of raising metadata-only not-implemented errors.
- MCP tool definitions include the seven report-assistant tools with schemas and descriptions.
- Tool calls return JSON text content through the stdio adapter.
- Mock context/draft/table/write-confirmation flows work without real CRM credentials.
- Unconfirmed writes do not call mock transport.
- Confirmed writes require the exact daily/weekly confirmation phrases and signed confirmation packages.
- No output contains raw GraphQL, endpoint values, auth headers, tokens, cookies, or raw error stacks.
- CRM package tests and lint pass.
