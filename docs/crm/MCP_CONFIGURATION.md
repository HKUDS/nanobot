# CRM MCP Configuration

This document records safe configuration patterns for the CRM MCP Server. The checked-in 15H example verifies Nanobot config parsing only; it does not start a real CRM connection.

## Current Status

- The CRM MCP Server is currently a mock, read-only, sanitized implementation.
- Task 15H adds a Nanobot mock-mode config example and schema parse test only.
- `crm_smoke_check` is a diagnostics tool.
- `crm_list_projects` is a mocked read tool backed by synthetic mocked GraphQL responses.
- Future real smoke can only happen in task 15I, after explicit user approval, with runtime configuration provided outside chat.

The current implementation does not provide a production CRM HTTP transport, active Nanobot runtime wiring, DingTalk integration, or CRM writeback.

## Allowed Tools

Current mock-mode examples should enable only these tools:

- `crm_smoke_check`
- `crm_list_projects`

Do not expose tools for:

- Raw GraphQL passthrough.
- Mutation.
- Create, update, delete, assign, contact, message, export, or writeback actions.
- DingTalk write or send integration.

## Stdio MCP Example

The checked-in 15H mock-mode example is `docs/crm/examples/nanobot-crm-mcp.mock.yaml`.

It uses this shape:

```yaml
tools:
  mcpServers:
    crm:
      type: stdio
      command: uv
      args:
        - run
        - --project
        - crm_mcp_server
        - python
        - -m
        - crm_mcp_server
      enabledTools:
        - crm_smoke_check
        - crm_list_projects
      toolTimeout: 30
```

Status note: this example is a mock-mode config shape and future run command example. The 15H test verifies that Nanobot's real `Config` schema can parse it. It does not prove that `python -m crm_mcp_server` starts a working MCP process.

15H does not write user runtime config. To use this later, copy or merge the example into a local Nanobot config outside this repository after the MCP process entrypoint is verified.

## HTTP MCP Example

This is a future deployment option only. Task 15H does not implement an HTTP MCP server.

```yaml
tools:
  mcpServers:
    crm:
      type: streamableHttp
      url: http://localhost:8765/mcp
      enabledTools:
        - crm_smoke_check
        - crm_list_projects
      toolTimeout: 30
```

The MCP HTTP URL is a mock/local CRM MCP Server endpoint placeholder. It is not the CRM GraphQL source endpoint.

## Docker And Compose Guidance

Future containerization should keep the CRM MCP Server image separate from the Nanobot image.

Rules:

- Do not bake `.env*` files into the image.
- Do not write tokens into Dockerfiles, Compose files, docs, tests, fixtures, or `.dek` artifacts.
- Inject runtime configuration only through the local runtime environment or a secret manager outside chat.
- Use placeholder variable names in examples, not concrete values.
- Do not run or record plain Compose config output because it can expand environment-derived values.

Safe syntax-only check when needed:

```bash
docker compose config --quiet
```

Example future service shape, not applied in 15G:

```yaml
services:
  crm-mcp-server:
    image: crm-mcp-server:local
    environment:
      CRM_GRAPHQL_ENDPOINT: ${CRM_GRAPHQL_ENDPOINT}
      CRM_GRAPHQL_TOKEN: ${CRM_GRAPHQL_TOKEN}
```

The placeholder environment keys above document expected names only. They are not concrete credentials and must not be committed with real values.

## Token Handling

- 15G does not need a token.
- 15H mock mode does not need a token.
- 15I optional real smoke is the first task that may need a token, and only after explicit user approval.
- Do not send tokens to chat.
- Do not write tokens into docs, `.dek`, tests, fixtures, git, screenshots, logs, or memory.
- The user should configure runtime values outside chat and outside documentation.

For future 15I only, the local operator configures `CRM_GRAPHQL_ENDPOINT` and `CRM_GRAPHQL_TOKEN` in the runtime environment outside chat. Do not put those values in docs, examples, tests, fixtures, or `.dek`.

Placeholder values, not assignments:

```bash
CRM_GRAPHQL_ENDPOINT -> <CRM_GRAPHQL_ENDPOINT>
CRM_GRAPHQL_TOKEN -> <CRM_GRAPHQL_TOKEN>
```

OpenCode should not run commands that print the environment, including `env`, `printenv`, or plain Compose config output. Real smoke output must be limited to sanitized status, counts, operation names, and error categories.

## Manual Verification

15H mock config wiring can be checked with:

```bash
uv run --extra dev pytest tests/config/test_crm_mcp_config.py
uv run --extra dev pytest crm_mcp_server/tests
uv run --extra dev ruff check tests/config/test_crm_mcp_config.py crm_mcp_server
```

Ruff does not validate Markdown content, but running the existing package lint remains a useful no-regression check.

Use this docs safety assertion to check for obvious secret-bearing examples. The forbidden strings are assembled so the documentation does not contain the exact markers being checked.

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

If the local shell does not provide `python`, run the same assertion with the project Python through `uv run python` and record that substitution.
