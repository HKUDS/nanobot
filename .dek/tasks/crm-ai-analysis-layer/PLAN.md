# CRM AI Analysis Layer Initial Plan

> This is an initial planning artifact only. Per user instruction, do not write business code in this phase.

Task id: `crm-ai-analysis-layer`

## Goal

Build a first-version AI analysis layer on top of the current Nanobot Docker project for read-only access to a self-developed CRM, supporting CLI and DingTalk, automated sales daily/weekly reports, and cross-sales opportunity dashboard summaries, delivered through the existing Docker workflow.

## Guardrails

- Do not write real CRM business data into `.dek`, `memory/history.jsonl`, `memory/MEMORY.md`, `SOUL.md`, `USER.md`, or any long-term memory path.
- Do not request or read tokens, secrets, credentials, or real customer data.
- Keep CRM access read-only in v1.
- Use synthetic fixtures or mocked interfaces for tests.
- Treat `.env*` as sensitive and do not inspect it during planning or implementation.
- Prefer changes that preserve existing Docker delivery behavior.

## Scope

- Inspect and use existing Nanobot extension points: CLI, DingTalk channel, tools/MCP, skills, cron/heartbeat, providers, and memory controls.
- Define a read-only CRM analysis path for daily reports, weekly reports, and cross-sales opportunity dashboard summaries.
- Support both interactive CLI queries and scheduled/triggered DingTalk delivery.
- Deliver through the existing Dockerfile and docker-compose workflow.

## Out Of Scope

- Writing CRM business code in this planning phase.
- Reading or storing real CRM data.
- Writing to CRM.
- Adding new long-term memory behavior for CRM data before explicit approval.
- Changing provider credentials or requesting secrets.

## Initial Architecture Direction

The safest first architecture is to keep CRM data access behind a read-only boundary and expose only analysis-safe operations to Nanobot. Two viable extension paths exist:

1. MCP-based CRM adapter: implement a separate read-only CRM MCP server and configure it in `tools.mcpServers` with `enabledTools` allow-listing.
2. Native read-only CRM tools: implement `Tool` subclasses and register them in `AgentLoop` if the CRM adapter must run in-process.

Given the need to avoid storing real CRM data in long-term memory and to preserve Docker delivery, the initial recommendation is MCP unless there is a strong operational reason to keep CRM access inside Nanobot. MCP provides a clear process boundary and configurable tool allow-listing.

## Proposed Components

- CRM read-only adapter: exposes sanitized read-only operations for opportunities and report aggregates.
- CRM analysis skill: workspace or packaged skill containing report playbooks, output formats, and no raw customer data.
- Report scheduling: use `CronTool`/`CronService` for explicit daily and weekly report schedules; use heartbeat only if file-driven periodic task review is preferred.
- DingTalk delivery: use existing DingTalk channel and group/private routing.
- CLI access: use existing `nanobot agent -m` and interactive mode.
- Docker delivery: extend current Docker/Compose only if the CRM adapter introduces a new service or dependency.
- Memory/data-safety policy: ensure prompts and workflows instruct the agent not to persist CRM source data or generated reports into memory unless explicitly approved and sanitized.

## Implementation Steps

1. Clarify CRM read-only interface.
   Confirm whether CRM data should be accessed through internal HTTP API, database read replica, MCP server, or another adapter.

2. Define non-sensitive data contract.
   Create a synthetic schema for opportunities, activities, owners, stages, amounts, and timestamps, with no real customer data.

3. Choose adapter mechanism.
   Decide between MCP server and native in-process tools based on deployment, credential isolation, and operational ownership.

4. Specify report outputs.
   Define exact Markdown structures for sales daily report, sales weekly report, and cross-sales opportunity dashboard summary.

5. Define scheduling.
   Decide report time, timezone, DingTalk target routing, and whether daily/weekly jobs are created through cron config, agent `cron` tool, or documented setup commands.

6. Define memory exclusion behavior.
   Decide whether to disable Dream/long-term memory for CRM sessions, add a CRM-specific instruction file, or implement a stricter output/data policy around report generation.

7. Write tests first in a future implementation phase.
   Use synthetic CRM fixtures and mock adapters. Cover read-only enforcement, report formatting, DingTalk routing assumptions, CLI invocation path, and Docker/Compose configuration validation.

8. Implement the minimal vertical slice.
   Connect synthetic CRM data to one report type, expose through CLI, then add DingTalk delivery and weekly/dashboard variants.

9. Update Docker/Compose.
   If MCP is selected, add an adapter service or command wiring without embedding secrets in the image. If native tools are selected, keep the existing service layout unless new runtime dependencies require Docker changes.

10. Verify without real data.
    Run Python tests, targeted DingTalk tests, linting, and Docker/Compose configuration checks using synthetic data only.

## Verification Ideas

- Python unit tests: `pytest` or targeted `pytest tests/...` with synthetic CRM fixtures.
- Lint: `ruff check nanobot/`.
- Docker build smoke check: `docker build -t nanobot .` if dependencies or Dockerfile change.
- Compose config check: `docker compose config` if `docker-compose.yml` changes.
- WebUI checks are only needed if WebUI is touched: `cd webui && bun run test`, `cd webui && bun run lint`.
- Bridge build check is only needed if `bridge/` is touched: `cd bridge && npm run build`.

## Risks

- CRM data may accidentally enter session history or Dream memory if CRM sessions use default memory behavior without policy controls.
- `.env.nanobot` is referenced by Compose and currently not excluded by `.dockerignore`; implementation should avoid copying or inspecting env files and consider excluding `.env.nanobot` from Docker build context.
- DingTalk output may expose sensitive CRM information if redaction rules are not defined before implementation.
- Native tools would run inside the Nanobot process and may be harder to isolate than MCP.
- Scheduled reports require reliable timezone and destination configuration.

## Open Decisions Before Code

- Adapter mechanism: MCP or native tool.
- CRM read-only API contract.
- Report templates and required metrics.
- DingTalk target routing and scheduling.
- Memory exclusion/redaction policy for CRM outputs.
- Docker/Compose changes required for adapter delivery.

## Directory Placement Recommendations

### 1. CRM Adapter

Recommended placement: external MCP adapter package outside `nanobot/`, for example `crm_adapter/` or `crm-mcp-server/` at repo root if this repository owns the adapter.

Reason: Nanobot already supports MCP servers through `tools.mcpServers`, wraps MCP tools as native tools, and supports `enabledTools` allow-listing. Keeping CRM access outside Nanobot gives the read-only CRM boundary a clear process/package boundary and avoids modifying core agent code for CRM-specific data access.

Evidence: `nanobot/config/schema.py:237-248`, `nanobot/config/schema.py:256-264`, `nanobot/agent/loop.py:414-434`, `nanobot/agent/tools/mcp.py:433-540`, `docs/configuration.md:918-990`

Alternative if MCP is rejected: add native read-only tools under `nanobot/agent/tools/crm.py` or a focused package such as `nanobot/agent/tools/crm/`. This is less isolated because built-in tools are registered from `AgentLoop._register_default_tools`.

Evidence: `nanobot/agent/tools/base.py:117-172`, `nanobot/agent/tools/registry.py:8-23`, `nanobot/agent/loop.py:360-412`

### 2. Daily/Weekly Report Generator

Recommended placement: a CRM-specific application package, for example `nanobot/crm/`, with report generation under `nanobot/crm/reports.py` or `nanobot/crm/reports/` if implemented in-process.

Reason: report generation is domain logic, not a generic agent tool, channel, provider, or memory primitive. A separate `nanobot/crm/` package keeps CRM report formatting, aggregation, and redaction policy away from `nanobot/agent/loop.py`, `nanobot/channels/dingtalk.py`, and generic tool code.

Evidence: current top-level package boundaries from directory listing of `nanobot/`; built-in tools are under `nanobot/agent/tools/`; channels are under `nanobot/channels/`; providers are under `nanobot/providers/`; memory lives under `nanobot/agent/memory.py`.

Alternative if using MCP fully: keep report generation inside the CRM MCP adapter and expose already-aggregated, read-only report tools to Nanobot. This further reduces CRM-specific code in Nanobot.

Evidence: MCP wraps tools/resources/prompts from external servers as native Nanobot tools in `nanobot/agent/tools/mcp.py:433-584`.

### 3. CLI Command Entry

Recommended placement for user-facing command: `nanobot/cli/commands.py`, ideally delegating implementation to `nanobot/crm/` instead of embedding CRM logic in the CLI file.

Reason: the package CLI entry point maps to `nanobot.cli.commands:app`, the Typer app is created in `commands.py`, and existing top-level CLI commands are defined there.

Evidence: `pyproject.toml:109-110`, `nanobot/cli/commands.py:74-79`, grep result for top-level commands at `nanobot/cli/commands.py:305`, `nanobot/cli/commands.py:515`, `nanobot/cli/commands.py:609`, `nanobot/cli/commands.py:1033`, `nanobot/cli/commands.py:1476`

Alternative: avoid a new CLI command and use the existing `nanobot agent -m "..."` flow plus a CRM skill/MCP tools. This avoids touching CLI code, but gives less structured command UX for reports.

Evidence: `docs/cli-reference.md:8-13`, `nanobot/cli/commands.py:1032-1091`

### 4. DingTalk Channel Or Command Handler

Recommended placement for DingTalk delivery: do not add CRM-specific logic to `nanobot/channels/dingtalk.py`; use existing `MessageTool`/OutboundMessage routing to send report output to DingTalk.

Reason: `DingTalkChannel` already handles transport-specific send/receive behavior, while `MessageTool` is the generic channel delivery path. CRM report generation should produce content and target `channel="dingtalk"`/`chat_id`, not fork DingTalk transport code.

Evidence: `nanobot/agent/tools/message.py:14-31`, `nanobot/agent/tools/message.py:109-181`, `nanobot/channels/dingtalk.py:657-705`

Recommended placement for slash/in-chat commands: `nanobot/command/` only if a real slash command such as `/crm-daily` is required, with registration through `register_builtin_commands` or a future command-plugin mechanism.

Reason: slash command routing is centralized in `nanobot/command/router.py` and built-ins are registered in `nanobot/command/builtin.py`, then wired into `AgentLoop`.

Evidence: `nanobot/command/router.py:27-98`, `nanobot/command/builtin.py:473-487`, `nanobot/agent/loop.py:318-324`

Alternative: avoid slash command changes and trigger reports through `CronTool`, existing natural-language CLI/DingTalk prompts, and CRM skills. This avoids modifying command core.

Evidence: `nanobot/agent/tools/cron.py:17-51`, `nanobot/agent/tools/cron.py:126-190`, `nanobot/cron/service.py:476-520`

### 5. Tests

Recommended test directories:

- Adapter tests: `tests/tools/` or a new `tests/crm/` if native/in-process; adapter package tests inside the external MCP adapter package if MCP is separate.
- Report generator tests: `tests/crm/` with synthetic fixtures only.
- CLI command tests: `tests/cli/`.
- DingTalk routing/delivery tests: `tests/channels/`, only for channel integration behavior; do not duplicate existing DingTalk transport tests unless behavior changes.
- Cron/scheduling tests: `tests/cron/` for cron job behavior, or `tests/heartbeat/` only if heartbeat is used.
- Config tests: `tests/config/` if adding config schema fields.

Reason: the current test tree mirrors runtime package domains.

Evidence: directory listing of `tests/`; existing DingTalk tests in `tests/channels/test_dingtalk_channel.py:81-119`; pytest config in `pyproject.toml:154-156`

### 6. Core Files To Avoid Modifying

Avoid modifying these core files unless there is a specific extension limitation:

- `nanobot/agent/loop.py`: central agent loop, tool registration, command wiring, persistence, memory scheduling.
- `nanobot/agent/runner.py`: provider/tool execution loop.
- `nanobot/agent/memory.py`: MemoryStore and Dream long-term memory behavior.
- `nanobot/channels/dingtalk.py`: DingTalk transport implementation.
- `nanobot/channels/manager.py`: channel lifecycle and outbound dispatch.
- `nanobot/providers/factory.py` and `nanobot/providers/registry.py`: LLM provider selection.
- `nanobot/config/schema.py`: global config schema.
- `nanobot/agent/tools/mcp.py`: generic MCP bridge.
- `nanobot/command/router.py`: generic slash command router.

Reason: these files provide generic Nanobot runtime infrastructure. CRM-specific behavior can usually sit behind MCP, a CRM package, a skill, or existing message/cron flows.

Evidence: `nanobot/agent/loop.py:300-324`, `nanobot/agent/loop.py:360-434`, `nanobot/agent/loop.py:1222-1259`, `nanobot/agent/memory.py:39-65`, `nanobot/agent/memory.py:706-778`, `nanobot/channels/dingtalk.py:657-705`, `nanobot/providers/factory.py:21-92`, `nanobot/providers/registry.py:1-11`, `nanobot/agent/tools/mcp.py:433-584`, `nanobot/command/router.py:27-98`

### 7. If Core Files Must Change

Modify `nanobot/agent/loop.py` only if native CRM tools must be registered as built-in tools. Alternative: expose CRM through MCP and configure `tools.mcpServers` with `enabledTools`.

Evidence: native tools are registered in `nanobot/agent/loop.py:360-412`; MCP servers are connected in `nanobot/agent/loop.py:414-434` and configured in `nanobot/config/schema.py:237-248`.

Modify `nanobot/cli/commands.py` only if a first-class `nanobot crm ...` CLI command is required. Alternative: use existing `nanobot agent -m` and CRM skill/MCP tools.

Evidence: CLI entry point is `pyproject.toml:109-110`; Typer app lives in `nanobot/cli/commands.py:74-79`; `agent` command already accepts `--message` and runtime config/workspace options in `nanobot/cli/commands.py:1032-1091`.

Modify `nanobot/command/builtin.py` only if CRM slash commands must be available in DingTalk/chat. Alternative: use natural-language prompts, existing cron jobs, or implement a command-plugin mechanism instead of hard-coding CRM commands.

Evidence: built-in slash commands are registered in `nanobot/command/builtin.py:473-487`; router dispatch lives in `nanobot/command/router.py:27-98`.

Modify `nanobot/config/schema.py` only if CRM needs first-class Nanobot config fields. Alternative: keep CRM adapter config in an external MCP server config, environment variables provided to that adapter, or workspace files that contain no secrets.

Evidence: `Config` root currently includes generic `agents`, `channels`, `providers`, `api`, `gateway`, and `tools` in `nanobot/config/schema.py:267-275`; MCP server config already supports command/url/env/headers/enabled tools in `nanobot/config/schema.py:237-248`.

Modify `docker-compose.yml` only if the CRM adapter runs as an additional service or needs explicit wiring. Alternative: use stdio MCP inside the existing container, or connect Nanobot to a separately deployed internal MCP/CRM endpoint through config.

Evidence: current services are `nanobot-gateway`, `nanobot-api`, and `nanobot-cli` in `docker-compose.yml:17-57`; Docker deployment already builds from the repo Dockerfile in `docs/deployment.md:3-12`.

Modify `nanobot/channels/dingtalk.py` only for generic DingTalk transport capability gaps, not CRM-specific report behavior. Alternative: send CRM report content through `MessageTool` to `channel="dingtalk"`.

Evidence: DingTalk send/inbound behavior already exists in `nanobot/channels/dingtalk.py:657-705`; generic message delivery is implemented in `nanobot/agent/tools/message.py:109-181`.

Modify `nanobot/agent/memory.py` only if there is no other way to prevent CRM data persistence. Alternative: keep CRM outputs out of long-term memory via workflow instructions, separate CRM sessions/workspace policy, sanitized summaries, or disable Dream/auto-memory behavior for CRM workflows if supported by config or future scoped policy.

Evidence: session turn persistence occurs in `nanobot/agent/loop.py:1222-1259`; durable memory/Dream behavior is in `nanobot/agent/memory.py:39-65` and `nanobot/agent/memory.py:706-778`.
