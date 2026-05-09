# CRM Manual Test Guide

This guide records safe manual checks for CRM opportunity intelligence documentation and future MCP work.

Do not use real CRM data, tokens, secrets, endpoint auth headers, or raw CRM payloads in these tests.

## Safety Preconditions

- Do not read local `.env*` files.
- Do not access real CRM unless the specific future MCP smoke section is explicitly approved by the user/operator.
- Do not paste credentials, auth headers, cookies, customer records, project names, contact details, or generated production reports into terminal output, docs, `.dek`, logs, memory, or chat.
- Use synthetic/mock data for default CLI and Docker checks.
- Treat `.dek` as development governance only.

## Mock CLI Smoke

Purpose: verify Nanobot mock/report/metrics/evidence path without real CRM access.

Commands:

```bash
nanobot crm report daily --adapter mock --date 2026-01-15 --scope synthetic-team
nanobot crm report weekly --adapter mock --start 2026-01-12 --end 2026-01-18 --scope synthetic-team
nanobot crm report dashboard --adapter mock --start 2026-01-01 --end 2026-01-31 --scope synthetic-team
```

Expected safe result:

- Command exits successfully.
- Output uses synthetic data only.
- Output includes deterministic metric names and values.
- Output includes evidence trace ids or an evidence section.
- Output does not include credentials, auth headers, raw CRM payloads, or real customer data.

Failure handling:

- If the command fails due to missing local dependencies, record only the command and sanitized error category.
- Do not work around failures by reading real CRM configuration.

## Docker Mock Smoke

Purpose: verify Docker delivery can run mock CRM reporting without `.dek` as runtime input and without real CRM secrets.

Commands:

```bash
docker build -t nanobot-crm-smoke .
docker run --rm nanobot-crm-smoke crm report daily --adapter mock --date 2026-01-15 --scope synthetic-team
```

Optional Compose syntax check:

```bash
docker compose config --quiet
```

Do not run plain `docker compose config` unless you have already confirmed it cannot print secrets from local `.env*` files or other environment sources in the current setup. If that cannot be confirmed, do not run it.

Expected safe result:

- Docker build succeeds without requiring CRM credentials.
- Docker run prints synthetic mock report output.
- No `.dek` runtime dependency is required for the mock report.
- No real CRM endpoint, auth header, token, secret, or raw CRM payload appears in output.

Safety note: plain `docker compose config` can expand environment-derived values in terminal output depending on local setup. Do not write Compose-expanded environment output into docs, `.dek`, logs, memory, or chat.

## Future MCP Smoke

Purpose: verify only the CRM MCP Server boundary and tool contract after implementation exists.

This section is not approved for execution during documentation-only work.

Preconditions before any future real MCP smoke:

- User/operator explicitly approves real CRM access for that session.
- Runtime configuration is provided outside chat and outside `.dek`.
- The MCP server has a read-only operation allow-list.
- The smoke uses the smallest safe scope and lowest safe limits.
- The smoke output is sanitized to status categories, counts, operation names, and source-reference shape only.

Future safe checks:

```text
1. Call crm_check_read_boundary.
2. Confirm read_only is true and mutations_allowed is false.
3. Confirm allowed_operations contains query names only.
4. Call one report-facts tool with a minimal approved scope.
5. Record only sanitized status, count, metric names, unavailable metric names, and evidence/source reference ids.
```

Never record:

- Credentials.
- Auth headers.
- Raw GraphQL request or response payloads.
- Customer names, contact details, phone numbers, email addresses, physical addresses, attachments, or free-text CRM notes.
- Generated production reports.

15I optional real smoke command, after explicit approval and runtime configuration outside chat. The default CRM GraphQL auth mode is `bearer`; use the default command unless you are intentionally comparing diagnostic modes:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke
```

Optional auth-mode diagnostic comparison, still read-only and still fixed to `listProject` limit `1`:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke --auth-mode private_token
uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke --auth-mode cookie
```

Record only sanitized status, reason, count fields, operation name, and error categories. If the result is `INCONCLUSIVE/config_missing`, stop and fix runtime configuration outside chat; do not broaden scope or print environment values.

## Confirmation-Gated Report Write Mock Check

Purpose: verify that report writeback is two-phase.

1. Generate a draft and confirmation package.
2. Verify no mutation is attempted before confirmation.
3. Confirm with `确认提交这份日报` or `确认提交这份周报`.
4. Verify only `createReport` is attempted.
5. Record only sanitized status, report id, report type, target, and mutation name.

17A `crm_list_projects` real-runtime library check, after explicit approval and runtime configuration outside chat:

- Default/mock mode must not access real CRM.
- Real mode must be explicitly enabled by the caller with `runtime_enabled=true`.
- Do not add CLI surface just for 17A if no helper exists.
- Record only sanitized status, reason, count fields, operation name, auth mode category, HTTP/status categories, and pagination counters.
- Never record endpoint values, tokens, auth header values, raw GraphQL request/response/error text, variables, project names, customer names, contact details, amount-like fields, addresses, or free-text notes.

17B `crm_list_business_chances` real-runtime library check, after explicit approval and runtime configuration outside chat:

- Default/mock mode must not access real CRM.
- Real mode must be explicitly enabled by the caller with `runtime_enabled=true`.
- Do not add CLI surface just for 17B if no helper exists.
- If a dedicated real business-chance check is added later, limit it to `max_records=1` and record only sanitized status, reason, count fields, operation name, auth mode category, HTTP/status categories, pagination counters, and source-reference shape.
- The existing optional real-smoke command below only confirms bearer `listProject` smoke; it does not prove a real `list_business_chance` read.
- Never record endpoint values, tokens, auth header values, raw GraphQL request/response/error text, variables, project names, customer names, contact details, amount-like fields, addresses, or free-text notes.

Safe 17B verification commands without real CRM access:

```bash
uv run --extra dev pytest crm_mcp_server/tests/test_list_business_chances.py
uv run --extra dev pytest crm_mcp_server/tests
uv run --extra dev ruff check crm_mcp_server
```

## Mock MCP Configuration Checks

Purpose: verify the CRM MCP Server mock-mode Nanobot configuration example without enabling real CRM access.

The checked-in mock config example is verified through Nanobot's real config schema. It starts the mock-mode stdio MCP server, but it does not apply user runtime config, start an HTTP MCP server, configure real CRM endpoint/token/headers, perform real CRM writeback, or run real CRM smoke.

Allowed current tools for mock-mode stdio examples:

- `crm_collect_sales_daily_context`
- `crm_collect_sales_weekly_context`
- `crm_collect_presales_weekly_context`
- `crm_generate_sales_daily_draft`
- `crm_generate_sales_weekly_draft`
- `crm_generate_presales_weekly_table`
- `crm_create_report_after_confirmation`

Forbidden tools and behaviors:

- Raw GraphQL passthrough.
- Raw mutation passthrough.
- Update, delete, assign, contact, message, export, or unrestricted writeback tools.
- DingTalk write or send integration.

The checked-in stdio mock example is `docs/crm/examples/nanobot-crm-mcp.mock.yaml`. It runs `python -m crm_mcp_server` as a mock-mode stdio MCP server. Use `python -m crm_mcp_server --metadata` when you only need safe metadata inspection.

Token handling:

- 15G does not need a token.
- Mock-mode stdio does not need a token.
- 15I optional real smoke is the first task that may need a token, and only after explicit user approval.
- Tokens must be configured by the user outside chat and outside docs.
- Do not run `env`, `printenv`, or plain Compose config output commands in this workflow.

For future 15I only, the local operator configures `CRM_GRAPHQL_ENDPOINT` and `CRM_GRAPHQL_TOKEN` in the runtime environment outside chat. Do not put those values in docs, examples, tests, fixtures, or `.dek`.

Placeholder values, not assignments:

```bash
CRM_GRAPHQL_ENDPOINT -> <CRM_GRAPHQL_ENDPOINT>
CRM_GRAPHQL_TOKEN -> <CRM_GRAPHQL_TOKEN>
```

Default 15H verification:

```bash
uv run --extra dev pytest tests/config/test_crm_mcp_config.py
uv run --extra dev pytest crm_mcp_server/tests
uv run --extra dev ruff check tests/config/test_crm_mcp_config.py crm_mcp_server
```

Do not run a real MCP server for this check. Do not set CRM credentials.

Docs safety assertion. The forbidden strings are assembled so the documentation does not contain the exact markers being checked.

```bash
python - <<'PY'
from pathlib import Path

paths = [
    Path("docs/crm/README.md"),
    Path("docs/crm/MCP_SERVER_DESIGN.md"),
    Path("docs/crm/MANUAL_TEST.md"),
    Path("docs/crm/MCP_CONFIGURATION.md"),
    Path("crm_mcp_server/README.md"),
]
for path in paths:
    if not path.exists():
        continue
    text = path.read_text()
    forbidden = [
        "fake-token" + "-123",
        "Bear" + "er ",
        "Author" + "ization:",
        "NANOBOT_API" + "_KEY=",
        "docker compose config" + "\n",
    ]
    hits = [item for item in forbidden if item in text]
    assert not hits, (path, hits)
print("15G docs safety assertions passed")
PY
```

## Documentation Audit Check

Purpose: verify the canonical docs remain documentation-only.

Checklist:

- `docs/crm/README.md` points to the canonical CRM docs.
- `docs/crm/GRAPHQL_CONTRACT.md` supersedes `docs/crm-graphql-contract.md`.
- `docs/crm/MCP_SERVER_DESIGN.md` contains design only, no implementation code.
- `docs/crm/MCP_TOOL_CONTRACT.md` contains tool contracts only, no implementation code.
- `docs/crm/MCP_CONFIGURATION.md` contains future-only stdio, HTTP, Docker, Compose, and token-handling examples with placeholders only.
- `docs/crm/MANUAL_TEST.md` uses mock CLI, Docker mock smoke, and future MCP smoke safety steps only.
- `docs/crm/MIGRATION_NOTES.md` explains what is retained, superseded, deferred, and removable later.
- `docs/crm/DOCS_INVENTORY.md` classifies all CRM docs and keeps delete approval as `No` unless explicitly approved later.
