# Spec: Upstream Merge Conflict Resolution

Date: 2026-02-26
Owner: jing1 + Codex
Branch: `chore/merge-upstream-20260226`
Status: Resolved (pending final diff review and commit)

## Background

We pulled `upstream/main` into a local integration branch and hit merge conflicts.
Resolved conflict files (2026-02-27):

1. `nanobot/agent/context.py`
2. `nanobot/agent/loop.py`
3. `nanobot/agent/tools/mcp.py`
4. `nanobot/cli/commands.py`
5. `nanobot/config/schema.py`

## Current State

1. Merge conflicts: resolved (`git diff --name-only --diff-filter=U` is empty).
2. Targeted regression tests: passed (`12 passed`).
3. Branch status: waiting for final diff review and commit decision.

## Goals

1. Resolve all conflicts without losing intentional local behavior.
2. Confirm conflict decisions with user one file at a time.
3. Keep build/test behavior stable after merge.

## Non-Goals

1. Large refactor unrelated to conflict resolution.
2. Functional redesign outside conflicted code unless required for compatibility.

## Decision Policy

1. Prefer upstream changes when they are bug fixes or compatibility updates.
2. Prefer local changes when they encode project-specific behavior.
3. If both sides contain valid logic, produce a merged implementation and confirm with user.

## Execution Plan

1. Start from `git diff --name-only --diff-filter=U`.
2. For each conflicted file:
   - Extract conflict blocks.
   - Summarize "local vs upstream" differences.
   - Ask user to choose: keep local / keep upstream / hybrid.
   - Apply edits and remove conflict markers.
3. After all files are resolved:
   - Run minimal validation (targeted tests or lint if available).
   - Recheck clean merge state: `git status`.

## Per-File Confirmation Template

For each file, record:

1. File path
2. Main conflict topics
3. User decision
4. Final merge strategy
5. Validation result (if any)

## Decision Log

### 2026-02-26 - `nanobot/agent/context.py`

1. Main conflict topics:
   - Runtime metadata injection location
   - Prompt/body time metadata duplication
   - Buffered media + collected message support
2. User decision:
   - Keep `_RUNTIME_CONTEXT_TAG` + `_build_runtime_context` flow
   - Keep local `current_metadata`/`collected_messages` capability
   - Avoid duplicating runtime/session metadata in system prompt
3. Final merge strategy:
   - Runtime metadata stays as a separate untrusted user message
   - User content keeps timestamp append + interleaved buffered media logic
   - System prompt remains stable (no per-message runtime injection)

### 2026-02-27 - `nanobot/channels/telegram.py` (follow-up)

1. Main topic:
   - Sender prefix duplicated `current_time` in message content.
2. User decision:
   - Remove `current_time` from sender prefix.
3. Final strategy:
   - Keep `message_id` in sender prefix for reaction/reply targeting.
   - Keep message time through `InboundMessage.timestamp` -> `ContextBuilder` path only.

### 2026-02-27 - `nanobot/agent/loop.py`

1. Main conflict topics:
   - `/stop` task cancellation path (`run` / `_handle_stop` / `_dispatch`)
   - `ExecTool.path_append` config propagation
   - Session persistence strategy (`_save_turn` vs `_save_session_with_tools`)
2. User decision:
   - Keep `_save_session_with_tools` as the persistence backbone.
   - Borrow `_save_turn` idea for better tool-output organization.
3. Final strategy:
   - Keep local loop architecture (stashed-content + silent marker + ack flow).
   - Merge upstream cancellation runtime pieces: `_active_tasks`, `_processing_lock`, `/stop`, `_dispatch`.
   - Add `path_append=self.exec_config.path_append` when registering `ExecTool`.
   - Keep virtual tool summary, but store it as structured JSON with truncated tool results.

### 2026-02-27 - `nanobot/agent/tools/mcp.py`

1. Main conflict topics:
   - Broken conflict splice inside `MCPTool.execute`.
   - Streamable HTTP timeout behavior.
2. User decision:
   - Keep local `MCPManager` architecture and remove broken legacy splice.
3. Final strategy:
   - Preserve `MCPManager/MCPTool` flow and compatibility helper `connect_mcp_servers`.
   - Add `timeout=None` to header-based HTTP client creation to avoid premature 5s default timeout.

### 2026-02-27 - `nanobot/cli/commands.py`

1. Main conflict topics:
   - Heartbeat interval display: fixed text vs config-driven.
   - MCP status display block.
2. User decision:
   - Keep both dynamic heartbeat display and MCP status output.
3. Final strategy:
   - Render `Heartbeat: every {hb_cfg.interval_s}s`.
   - Keep enabled/disabled MCP summary output.

### 2026-02-27 - `nanobot/config/schema.py`

1. Main conflict topic:
   - Import conflict between `Literal` and `AliasChoices`.
2. User decision:
   - Keep both imports for compatibility.
3. Final strategy:
   - Preserve `from typing import Literal`.
   - Preserve `AliasChoices` import in pydantic import line.

## Validation Log

1. `pytest -q tests/test_context_prompt_cache.py tests/test_context_buffered_media.py tests/test_task_cancel.py tests/test_agent_loop_stashed_content.py`
   - Result: `12 passed`
2. `python -m py_compile nanobot/agent/context.py nanobot/agent/loop.py nanobot/agent/tools/mcp.py nanobot/cli/commands.py nanobot/config/schema.py`
   - Result: pass

## Acceptance Criteria

1. No `<<<<<<<`, `=======`, `>>>>>>>` markers remain.
2. `git status` has no `UU` files.
3. User has confirmed every conflicted file decision.
4. Merge commit is ready once user approves final diff.

## Risks

1. Silent behavior drift if conflict blocks are merged mechanically.
2. Prompt/context behavior regressions in agent core files.
3. CLI config mismatches if schema and command updates diverge.

## Rollback Strategy

1. Keep conflict decisions documented before commit.
2. If merged result is incorrect, restore file from:
   - `HEAD` side, or
   - `upstream/main`, then re-apply confirmed edits.
