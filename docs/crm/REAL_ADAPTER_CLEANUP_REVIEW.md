# Real Adapter Cleanup Review

## Summary

CRM production direction is MCP-first: real CRM GraphQL access belongs behind the independent read-only CRM MCP Server.

The direct Nanobot `RealCRMAdapter` GraphQL route is superseded for production real CRM access. Its current value is historical/reference coverage for read-only normalization, pagination, redaction, and forbidden-write boundaries.

No files were deleted in this review. No files were moved, renamed, or archived.

15J Option B was selected after this review. The implemented Option B cleanup archives superseded docs in place and keeps direct adapter code/tests as reference. No code or test file was deleted, moved, renamed, or modified.

## Current Status

Task 15I is implemented but the optional real smoke status is sanitized `INCONCLUSIVE/config_missing`. The package-local smoke command recorded `runtime_enabled=false`, `http_status_category=not_attempted`, `data_count=0`, `normalized_count=0`, `graphql_errors_count=0`, `mutation_used=false`, and error category `config_missing`. The `.dek` handoff and evidence state that no real CRM request was made.

The MCP route currently has:

- `crm_smoke_check` as a read-only sanitized diagnostic tool.
- `crm_list_projects` as the first read-only mocked GraphQL data tool.
- Redaction and diagnostics helpers with tests for safe error shape, sensitive marker exclusion, and mutation/write-like exclusion.
- Docker, stdio MCP, HTTP MCP, token-handling, and safe verification docs.
- A mock-mode Nanobot MCP config example parsed by the real Nanobot config schema.

This review did not rerun real smoke, did not access real CRM, did not read `.env*`, and did not handle tokens.

## Inventory

| Path | Category | Reason | Recommended action | User approval required |
| --- | --- | --- | --- | --- |
| `nanobot/crm/models.py` | keep | Shared normalized models are still used by mock reports, metrics, evidence, CLI, and the historical direct adapter tests. | Keep in main tree. Do not treat as direct-adapter cleanup. | No |
| `nanobot/crm/adapters.py` | keep | Read-only `CRMAdapter` protocol remains useful for mock/report inputs and possible future `MCPCRMAdapter` or MCP tool adaptation. | Keep in main tree. | No |
| `nanobot/crm/mock_adapter.py` | keep | Synthetic mock adapter is still the safe local verification path. | Keep in main tree. | No |
| `nanobot/crm/metrics.py` | keep | Deterministic metrics remain the report source of truth. | Keep in main tree. | No |
| `nanobot/crm/evidence.py` | keep | Report-local evidence traces remain required for mock and future MCP-backed reports. | Keep in main tree. | No |
| `nanobot/crm/reports.py` | keep | Report assembly remains independent from the direct GraphQL route. | Keep in main tree. | No |
| `nanobot/crm/cli.py` | keep | Mock CLI remains the safe smoke and development entry. | Keep in main tree. | No |
| `nanobot/crm/graphql_client.py` | superseded-reference | Direct in-process GraphQL shell is fail-closed and tested with injected transport, but production GraphQL transport now belongs in the CRM MCP Server. | Keep as reference for now with stronger superseded header in a later approved cleanup, or archive after MCP replacement is mature. | Yes for edits, archive, or delete |
| `nanobot/crm/real_adapter.py` | superseded-reference | Direct in-process `RealCRMAdapter` normalizes mocked GraphQL responses and documents read-only behavior, but it is not the production route. | Keep as reference for now with stronger superseded header in a later approved cleanup, or archive after MCP replacement is mature. | Yes for edits, archive, or delete |
| `nanobot/crm/real_smoke_diagnostics.py` | needs-user-decision | Historical direct-route diagnostics still import `CRMGraphQLClient`, `_PROJECT_QUERY`, and `RealCRMAdapter`. It overlaps with the newer MCP `real_smoke.py` path and may confuse future agents. | Decide whether to keep with a strong superseded header, archive with direct-adapter material, or delete after confirming no task still needs it. | Yes |
| `tests/crm/test_graphql_client.py` | superseded-reference | Tests capture useful allow-list, mutation rejection, env-read exclusion, and redaction behavior for the direct client. They target a superseded route but preserve unique behavior checks. | Keep as reference until MCP tests cover equivalent behavior fully; consider adding superseded-route header later. | Yes for edits, archive, or delete |
| `tests/crm/test_real_adapter_contract.py` | superseded-reference | Tests document normalization expectations for projects, activities, reports, customers, business chances, pagination, missing fields, and absent writeback methods. | Keep as reference until MCP tools cover equivalent entity coverage; do not delete now. | Yes for edits, archive, or delete |
| `tests/crm/test_real_adapter_redaction.py` | superseded-reference | Tests document redaction and no-env/no-real-endpoint behavior for the direct adapter. | Keep as reference until MCP redaction coverage is stable and equivalent. | Yes for edits, archive, or delete |
| `tests/crm/test_real_smoke_diagnostics.py` | archive-candidate | Tests cover historical direct-route sanitized diagnostics and may be confusing because 15I moved real smoke to the CRM MCP Server package. | Consider archive or superseded header after user approval; keep until direct diagnostics decision is made. | Yes |
| `tests/crm/test_adapters.py` | keep | Tests the shared read-only `CRMAdapter` protocol, not only the direct adapter. | Keep in main tree. | No |
| `docs/crm-graphql-contract.md` | archived-in-place / superseded-reference | Root-level GraphQL contract is superseded by `docs/crm/GRAPHQL_CONTRACT.md` but retains historical direct Nanobot runtime-env framing. Option B marked it archived-in-place without moving or deleting it. | Keep only as historical migration reference. Do not use as canonical. Deletion is not recommended yet. | Yes for future move/delete |
| `docs/crm/GRAPHQL_CONTRACT.md` | keep | Canonical read-only GraphQL source contract for the CRM MCP Server. | Keep as canonical. | No |
| `docs/crm/MCP_SERVER_DESIGN.md` | keep | Canonical MCP server design and boundary document. | Keep as canonical. | No |
| `docs/crm/MCP_TOOL_CONTRACT.md` | keep | Canonical read-only MCP tool contract and diagnostics boundary. | Keep as canonical. | No |
| `docs/crm/MCP_CONFIGURATION.md` | keep | Canonical configuration guidance for Docker, stdio MCP, HTTP MCP, and token boundaries. | Keep as canonical. | No |
| `docs/crm/MANUAL_TEST.md` | keep | Safe mock and future approved smoke procedures. | Keep as canonical. | No |
| `docs/crm/MIGRATION_NOTES.md` | keep | Explains MCP-first migration and deletion gates. | Keep and link this cleanup review. | No |
| `docs/crm/DOCS_INVENTORY.md` | keep | Canonical inventory document. | Keep and update with this review classification. | No |
| `docs/crm/REAL_ADAPTER_CLEANUP_REVIEW.md` | keep | This 15J phase-one review records cleanup candidates without deleting or moving files. | Keep as the decision document for the next approved cleanup step. | No |
| `.dek/changes/crm-opportunity-intelligence/TASKS.md` | needs-user-decision | Contains useful task history and explicit 15J cleanup gate, but old task wording can still point future agents at the direct route if read out of context. | Keep now. Later add stronger archive notes or split old 14C-14F wording only after approval. | Yes for substantial edits or archival |
| `.dek/changes/crm-opportunity-intelligence/ARCHITECTURE.md` | keep | Already states MCP-first direction and marks the in-process route as superseded reference. | Keep as canonical architecture. | No |
| `.dek/tasks/crm-ai-analysis-layer/HANDOFF.md` | keep | Current handoff records 15I status and will point to this cleanup review. | Keep and update for 15J review completion. | No |
| `.dek/tasks/crm-ai-analysis-layer/PROGRESS.md` | keep | Current progress ledger. | Keep and update with 15J review completion and pending user decision. | No |
| `.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md` | keep | Evidence log for commands, scope confirmations, and verification. | Keep and update with 15J review evidence. | No |
| `crm_mcp_server/` | keep | Independent MCP-first package; not part of direct-adapter cleanup. | Keep as active route. | No |

## Recommended Cleanup Options

### Option A: Conservative

Keep all superseded code and tests in place. Add stronger headers and docs only, making the direct `RealCRMAdapter` route visibly reference-only.

Good when the team wants zero behavior risk and maximum historical context. Downside: direct-route files remain in the main tree and may continue to confuse future agents.

### Option B: Archive Docs Only

Move or mark superseded docs while keeping code and tests as reference. Candidate doc actions include archiving or strengthening the superseded notice for `docs/crm-graphql-contract.md`, while keeping `nanobot/crm/graphql_client.py`, `nanobot/crm/real_adapter.py`, and related tests in place.

Good balance for the current stage: it reduces documentation confusion while retaining code/tests until the MCP route proves stable with real runtime configuration.

### Option C: Remove Direct Adapter Code/Tests After MCP Replacement

Delete `nanobot/crm/real_adapter.py`, `nanobot/crm/graphql_client.py`, and related direct-route tests only after MCP tools cover equivalent functionality and the user explicitly approves deletion.

This should wait until MCP replacement is fully mature: MCP tools should cover the required read operations, normalization, redaction, diagnostics, and Nanobot integration path. Current 15I status is still `INCONCLUSIVE/config_missing`, so this option is premature.

## Recommended Choice

Recommended: Option B.

Selected: Option B. The current cleanup action is in-place documentation archival only.

At the current stage, archive or strongly mark superseded docs first, but keep direct adapter code/tests as reference. The MCP route has solid mocked tests and config docs, but the optional real smoke has not produced a real CRM connectivity result because 15I ended as sanitized `INCONCLUSIVE/config_missing` with no real request made.

Option C is not recommended now because deleting direct adapter code/tests would remove reference normalization and redaction knowledge before the MCP replacement has proven stable against real runtime configuration.

## Explicit Non-Actions

- No deletion.
- No file movement.
- No file rename.
- No runtime business code changes.
- No tests modified to skip the old path.
- No direct adapter code/test edits.
- No real CRM access.
- No real CRM smoke rerun.
- No `.env*` reads.
- No token handling.
- No raw GraphQL request or response output.
- No real customer, project, contact, amount, address, or free-text CRM data output.
- No DingTalk changes.
- No writeback or Mutation work.

## Proposed Next Prompt

Use only after explicit user approval of a cleanup option:

```text
执行 CRM MCP Server 任务 15J 第二阶段 cleanup。批准选项：[Option A / Option B / Option C]。

边界：不要访问真实 CRM，不要读取 `.env*`，不要输出 token/Auth/Bearer/raw GraphQL/真实客户项目数据，不要做 DingTalk，不要做 writeback 或 Mutation。

如果执行 Option A：只给 superseded direct GraphQL route 文件和相关测试/文档添加强 superseded-reference header，不删除、不移动。

如果执行 Option B：只归档或强标记 superseded docs，保留 `nanobot/crm/graphql_client.py`、`nanobot/crm/real_adapter.py` 和相关测试作为 reference。

如果执行 Option C：只有在 MCP tools 已覆盖等价功能且再次确认后，删除用户明确列出的 direct adapter code/tests，并运行相关 tests/lint/docs assertions。

请先使用 receiving-code-review 或 writing-plans 重新分解实际 cleanup，然后实施最小变更，最后更新 `docs/crm/DOCS_INVENTORY.md`、`docs/crm/MIGRATION_NOTES.md`、`.dek/tasks/crm-ai-analysis-layer/EVIDENCE.md`、`PROGRESS.md`、`HANDOFF.md`。
```
