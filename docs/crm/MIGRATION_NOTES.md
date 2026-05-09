# CRM Migration Notes

This document explains the migration from Nanobot in-process real CRM access to a separate read-first CRM MCP Server with exactly one confirmation-gated report write path.

## Decision

Real CRM access should move from an in-process Nanobot `RealCRMAdapter` that talks directly to GraphQL to a separate CRM MCP Server.

The CRM MCP Server becomes the production real CRM read-first access layer, plus the explicit confirmation-gated `createReport` path. Nanobot keeps mock/report/metrics/evidence behavior and connects to the MCP server through existing MCP configuration.

The direct in-process Nanobot GraphQL route is superseded for production. Future implementation must not expand `RealCRMAdapter` unless the user explicitly reopens that route.

## Why Move To MCP Server

The MCP route is preferred because it gives the CRM boundary a clearer process and ownership boundary.

Benefits:

- CRM credentials and auth headers stay outside Nanobot.
- The exposed tool surface can be explicitly allow-listed.
- Mutations can be rejected before any GraphQL transport execution.
- CRM-specific GraphQL transport, pagination, and redaction do not spread into Nanobot core.
- Nanobot can use its existing MCP configuration and tool discovery path.
- Future deployment can choose stdio, HTTP, or separate service without changing report semantics.
- Manual smoke tests can target the MCP boundary with sanitized output instead of exercising Nanobot internals against real CRM.

## Existing Code To Keep

Keep these existing Nanobot-side pieces unless a future approved plan says otherwise:

- `nanobot/crm/models.py`: normalized records, report request/window/scope, metrics, evidence, and report output dataclasses.
- `nanobot/crm/mock_adapter.py`: synthetic read-only adapter for local development.
- `nanobot/crm/synthetic_data.py`: synthetic CRM scenarios.
- `nanobot/crm/metrics.py`: deterministic metric computation.
- `nanobot/crm/evidence.py`: report-local evidence trace construction.
- `nanobot/crm/reports.py`: mock/report assembly path.
- `nanobot/crm/cli.py`: mock CLI verification entry.
- CLI, command, Docker, and test files that verify synthetic/mock report behavior.
- `nanobot/skills/crm-opportunity-intelligence/SKILL.md`: MCP-first usage and safety boundaries.

These retained pieces support development verification and report behavior without real CRM access.

## Existing Plans Superseded

The following plan direction is superseded:

- Continuing `.dek/changes/crm-opportunity-intelligence/TASKS.md` Task 14E and 14F as written.
- Treating `nanobot/crm/real_adapter.py` as the production real CRM access path.
- Treating `nanobot/crm/graphql_client.py` as the production GraphQL client path inside Nanobot.
- Using Nanobot-specific direct CRM GraphQL environment variables as the production integration model.
- Optional real CRM smoke through Nanobot internals as the next step.

The completed internal adapter work remains historical/reference material unless the user explicitly reopens that route.

## Documentation Migration

Canonical CRM documentation now lives under `docs/crm/`:

- `README.md`
- `GRAPHQL_CONTRACT.md`
- `MCP_SERVER_DESIGN.md`
- `MCP_TOOL_CONTRACT.md`
- `MANUAL_TEST.md`
- `MIGRATION_NOTES.md`
- `DOCS_INVENTORY.md`

The old `docs/crm-graphql-contract.md` is superseded by `docs/crm/GRAPHQL_CONTRACT.md` and kept temporarily for migration review.

Task 15J phase one produced `docs/crm/REAL_ADAPTER_CLEANUP_REVIEW.md` as the cleanup decision document. It inventories the superseded direct GraphQL / `RealCRMAdapter` route and recommends Option B for the current stage: archive or strongly mark superseded docs first, while keeping direct adapter code and tests as reference until the MCP path proves stable.

Option B is now selected and executed by Task 15K. `docs/crm-graphql-contract.md` is archived in place with a strong superseded-reference header. Direct adapter code and tests remain in place as reference material.

No files deleted. No Python code or tests were deleted under Option B. The retained code/tests are reference material for migration review, normalization ideas, redaction ideas, and safety boundaries, not the target for production CRM access expansion.

Cleanup requires explicit user approval. This migration note does not approve deletion, archival, file movement, or business-code changes.

## When Old Docs Can Be Deleted

Do not delete old docs in the current phase.

Old docs or sections can be deleted only after all of these are true:

- The user explicitly approves deletion.
- `docs/crm/DOCS_INVENTORY.md` marks the file or section as delete-approved.
- Unique facts have been migrated to canonical `docs/crm/` docs or intentionally dropped with approval.
- The MCP Server design and tool contract are approved.
- Any replacement implementation plan no longer references the old doc as a source of truth.

## When Old Code Can Be Deleted

Do not delete old code in the current phase.

Old internal real CRM code can be considered for deletion only after all of these are true:

- The CRM MCP Server exists and is approved as the only production real CRM access path.
- Nanobot MCP configuration can call approved CRM MCP tools: read tools plus the explicit confirmation-gated `createReport` path.
- Mock CLI and Docker smoke paths still pass without the old internal real adapter code.
- The GraphQL contract and MCP tool contract cover all facts needed from the old internal adapter tests.
- The user explicitly approves deleting or archiving the old code.

## Deferred Areas

- DingTalk CRM delivery remains deferred until the CRM MCP Server and Nanobot MCP configuration are settled.
- Arbitrary CRM writeback remains out of scope; only the explicit confirmation-gated `createReport` path is in v1, and any other write path requires a separate change proposal.
- System/internal CRM UI or BI dashboard work remains out of scope.
- Real CRM smoke remains opt-in and must not run without explicit user approval.

## Next Step

Review and approve the canonical docs in `docs/crm/`. After approval, write a new MCP-route implementation plan for the CRM MCP Server without continuing the old in-process `RealCRMAdapter` task path.
