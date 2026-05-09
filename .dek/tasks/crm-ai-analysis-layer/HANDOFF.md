# Handoff - CRM AI Analysis Layer

## Current State

Final review findings are fixed on the dirty local worktree. No commit was made. The CRM MCP stdio path now disables SDK input validation and relies on runtime normalization/sanitization. Confirmation package preparation now sanitizes caller-provided string `target` and string-list `to` values before signing/serialization.

## Done

- Added red test coverage for malicious string `target` and `to` values passed to `crm_create_report_after_confirmation`.
- Added red test coverage that `run_stdio_server_async` registers `call_tool` with `validate_input=False` using a monkeypatched fake MCP `Server`.
- Imported `sanitize_transport_detail` in `tool_runtime.py` and added `_safe_text` normalization.
- Changed `_target_argument` to sanitize unsafe string targets.
- Changed `_string_list` to sanitize string entries and filter empty/non-string entries.
- Changed `stdio_server.py` to use `@server.call_tool(validate_input=False)`.
- Preserved normal write-prep and confirmed mock-write behavior via focused report-write regression tests.

## Next

- User decision whether to commit, push, or open a PR.
- If continuing implementation, keep 17C as the next candidate only after confirming the intended real business-chance/read-report path.

## Key Files

- `crm_mcp_server/crm_mcp_server/tool_runtime.py` - runtime argument normalization for report assistant tools.
- `crm_mcp_server/crm_mcp_server/stdio_server.py` - live MCP stdio adapter registration.
- `crm_mcp_server/tests/test_tool_runtime.py` - confirmation package redaction regression coverage.
- `crm_mcp_server/tests/test_stdio_server.py` - MCP SDK registration regression coverage.
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md` - red/green and requested verification evidence.

## Verification

- `uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_tool_runtime.py crm_mcp_server/tests/test_stdio_server.py` - red run failed as expected with 2 failures before implementation.
- `uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests/test_tool_runtime.py crm_mcp_server/tests/test_stdio_server.py crm_mcp_server/tests/test_report_write.py` - pass, `42 passed, 1 warning` after fixes.
- `uv run --project crm_mcp_server --with pytest pytest crm_mcp_server/tests` - pass, `199 passed, 1 warning` after fixes.
- `uv run --project crm_mcp_server --with ruff ruff check crm_mcp_server tests/config/test_crm_mcp_config.py` - initially failed on import order, then pass after reordering imports.
- `uv run --with pytest --with pyyaml pytest tests/config/test_crm_mcp_config.py` - pass, `3 passed`.

## Risks / Blockers

- Worktree had many pre-existing dirty changes; only files relevant to the review findings and tracked task evidence/handoff were edited in this session.
- Package-local pytest commands still emit `PytestConfigWarning: Unknown config option: asyncio_mode`; tests pass.
- Do not record endpoint, token, auth header values, raw GraphQL request/response/error, variables, or real CRM record fields.
