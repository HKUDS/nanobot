# Handoff - CRM AI Analysis Layer

## Current State

17B is complete on branch `17a-real-crm-list-projects` from the current local `main` state. `crm_list_projects` and `crm_list_business_chances` now each have two paths: default/mock mode stays network-free, and explicit real mode requires `runtime_enabled=true` plus complete runtime config. Real mode reuses the sanitized bearer `RealGraphQLSmokeTransport` proven by 15I.

## Done

- Kept default `crm_list_projects` behavior from accessing real CRM.
- Added optional `runtime_enabled=false` and `transport=None` API support.
- Added explicit real-mode config loading only when `runtime_enabled=true` and no transport is injected.
- Added sanitized `config_missing`, HTTP/auth/unavailable/rate-limit, and GraphQL error handling for the project tool.
- Expanded project diagnostics with safe runtime/auth/transport categories only.
- Kept default `crm_list_business_chances` behavior from accessing real CRM.
- Added optional `runtime_enabled=false` and `transport=None` API support to `crm_list_business_chances`.
- Added explicit real-mode config loading only when `runtime_enabled=true` and no business-chance transport is injected.
- Added sanitized `config_missing`, HTTP/auth/unavailable/rate-limit, and GraphQL error handling for the business-chance tool.
- Expanded business-chance diagnostics with safe runtime/auth/transport categories only.
- Updated CRM tool contract, manual test guidance, and `.dek` evidence/progress.

## Next

- 17C candidate: add a dedicated approved sanitized real business-chance smoke/helper if `list_business_chance` shape needs validation, or proceed to real-mode daily report facts only after that read path is explicitly verified.

## Key Files

- `crm_mcp_server/crm_mcp_server/projects.py` - 17A implementation.
- `crm_mcp_server/crm_mcp_server/business_chances.py` - 17B implementation.
- `crm_mcp_server/tests/test_list_projects.py` - 17A TDD coverage.
- `crm_mcp_server/tests/test_list_business_chances.py` - 17B TDD coverage.
- `crm_mcp_server/tests/test_redaction.py` - diagnostics allow-list update.
- `docs/crm/MCP_TOOL_CONTRACT.md` - explicit real-mode contract.
- `docs/crm/MANUAL_TEST.md` - safe manual guidance.
- `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md` - detailed sanitized evidence.

## Verification

- `uv run --extra dev pytest crm_mcp_server/tests/test_list_business_chances.py` - pass, `22 passed in 0.03s`.
- `uv run --extra dev pytest crm_mcp_server/tests` - pass, `130 passed in 0.08s`.
- `uv run --extra dev ruff check crm_mcp_server` - pass, `All checks passed!`.

## Risks / Blockers

- Current worktree had pre-existing dirty changes from prior CRM MCP work; user chose to proceed from current local `main` with those changes carried forward.
- Do not run a real `crm_list_projects` manual check unless the user explicitly approves and confirms runtime config.
- Do not run a real `crm_list_business_chances` check unless the user explicitly approves, confirms runtime config, and a dedicated sanitized helper/path exists.
- The existing optional `real_smoke` command confirms bearer `listProject` only, not real `list_business_chance`.
- Do not record endpoint, token, auth header values, raw GraphQL request/response/error, variables, or real CRM record fields.
