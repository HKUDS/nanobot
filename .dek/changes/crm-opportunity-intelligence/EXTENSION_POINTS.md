# CRM Opportunity Intelligence Extension Points

Change id: `crm-opportunity-intelligence`

Purpose: confirm the Nanobot extension seams for the first implementation task without adding runtime code.

## Confirmed checklist

- [x] CLI: `nanobot/cli/commands.py` is the Typer entry point for first-class commands. First implementation should keep CRM logic outside this file and use it only as a thin CLI wrapper if a dedicated command is required.
- [x] Tools/MCP: `nanobot/agent/tools` is the native tool location, while MCP servers can be configured as external tools. V1 should prefer an isolated read-only adapter boundary and avoid CRM-specific changes to generic agent core unless a native built-in tool is explicitly chosen.
- [x] Skills: `nanobot/skills` is the built-in skill location. A CRM skill may document report usage, deterministic metrics, evidence traces, and no CRM writeback, but it must not contain real CRM data.
- [x] DingTalk: `nanobot/channels/dingtalk.py` is the DingTalk transport implementation. CRM report logic must not be placed in `nanobot/channels/dingtalk.py`.
- [x] Message delivery: `nanobot/agent/tools/message.py` is the generic outbound message path. DingTalk report delivery should use existing message/channel delivery instead of CRM-specific transport code.
- [x] Memory safety: `nanobot/agent/memory.py` contains long-term memory and Dream behavior. CRM workflows must avoid persisting raw CRM records, real CRM-derived report content, or CRM-derived conversation history to long-term memory.
- [x] Tests: `tests/` mirrors runtime package domains. CRM implementation should add synthetic-only tests under `tests/crm`, with CLI, tool, command, channel, and Docker tests added only when those surfaces are touched.
- [x] Docker smoke: `Dockerfile` and `docker-compose.yml` define delivery surfaces. Docker smoke checks should verify mock-mode CRM reporting without real secrets or `.dek` runtime dependency.

## Chosen first-version approach

- Start with synthetic mock data and `MockCRMAdapter` before any real CRM adapter.
- Keep report generation behind a CRM package boundary such as `nanobot/crm`.
- Keep metrics deterministic and independent from LLM, CLI, DingTalk, and real CRM client code.
- Use CLI verification before DingTalk integration.
- Use DingTalk only as a fixed report request/delivery surface after CLI is verified.
- Keep Docker production configuration unchanged until a task explicitly proves an adapter or smoke test requires a change.

## Runtime boundary

`.dek` is a development governance directory for requirements, architecture, task plans, progress, and evidence. production runtime must not depend on `.dek`, and `.dek` must not store real CRM data, real customer data, generated production reports, tokens, secrets, or CRM runtime cache.
