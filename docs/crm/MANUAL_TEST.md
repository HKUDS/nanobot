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

15I optional real smoke command, after explicit approval and runtime configuration outside chat:

```bash
uv run --project crm_mcp_server python -m crm_mcp_server.real_smoke
```

Record only sanitized status, reason, count fields, operation name, and error categories. If the result is `INCONCLUSIVE/config_missing`, stop and fix runtime configuration outside chat; do not broaden scope or print environment values.

## Mock MCP Configuration Checks

Purpose: verify the CRM MCP Server mock-mode Nanobot configuration example without enabling real CRM access.

15H verifies the checked-in mock config example through Nanobot's real config schema. It does not apply user runtime config, implement a server entrypoint, start an HTTP MCP server, or run real CRM smoke.

Allowed current tools for future mock-mode examples:

- `crm_smoke_check`
- `crm_list_projects`

Forbidden tools and behaviors:

- Raw GraphQL passthrough.
- Mutation.
- Create, update, delete, assign, contact, message, export, or writeback tools.
- DingTalk write or send integration.

The checked-in stdio mock example is `docs/crm/examples/nanobot-crm-mcp.mock.yaml`. Treat its `python -m crm_mcp_server` command as a config shape and future run command example until the actual MCP process entrypoint is verified.

Token handling:

- 15G does not need a token.
- 15H mock mode does not need a token.
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
