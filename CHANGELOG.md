# Changelog

All notable changes to Nanobot are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **Path disclosure hardening**: `DelegationDispatcher` now exposes only the workspace directory name (not the full absolute path) in delegation contracts (`delegation.py`)
- **Task input sanitisation**: `DelegateTool` and `DelegateParallelTool` now strip C0/C1 control characters and enforce a 4,000-character maximum before forwarding tasks to specialist agents (`delegate.py`)
- **Trivy scans on PRs**: Container image vulnerability scanning now runs on all pull requests, not only on push/schedule events (`.github/workflows/security.yml`)

### Added
- **`classify_reaction()` in agent layer**: Emoji → rating classification moved from `bus/events.py` to `nanobot/agent/reaction.py`, preserving the module boundary rule that `bus/` must not import from `agent/` (`reaction.py`, `loop.py`)
- **`FakeProvider` shared fixture**: Common scripted LLM provider consolidated into `tests/conftest.py` and re-used by `test_delegate.py`, `test_parallel_delegation.py`, and `test_routing_metrics.py`
- **Concurrent session isolation test**: `TestConcurrentProcessMessage.test_concurrent_sessions_independent` verifies that simultaneous `_process_message()` calls for different sessions do not corrupt each other's history (`test_agent_loop.py`)
- **Deploy-staging skip notification**: `notify-skipped` job emits a CI annotation when the upstream build did not succeed, making silent skips visible (`.github/workflows/deploy-staging.yml`)

### Changed
- **`run_tool_loop` context compression**: Message list is trimmed to the most recent 20 exchanges (preserving system messages) when it exceeds 40 messages, preventing unbounded token growth (`tool_loop.py`)
- **`AgentRegistry` caching**: `list_roles()` and `role_names()` now cache their results and invalidate on `register()` / `merge_register()`, eliminating repeated dict comprehension on every routing decision (`registry.py`)
- **Role-name matching uses word-boundary regex**: `Coordinator` text-scan fallback now uses a compiled `\b<role>\b` pattern (cached per role) instead of substring containment, reducing false positives (`coordinator.py`)
- **Swallowed exception now logged**: Silent `except Exception: pass` in coordinator span update replaced with `logger.debug(...)` for observability (`coordinator.py`)
- **`build_default_registry()` documented**: Docstring added explaining merge-over-defaults behaviour (`coordinator.py`)
- **`Scratchpad.read()` returns `None`**: Returns `str | None` instead of sentinel strings for missing/empty state; callers (`ScratchpadReadTool`) produce the human-readable messages (`scratchpad.py`, `tools/scratchpad.py`)
- **Import-check CI step installs package first**: `pip install -e ".[dev]"` added before the boundary-violation check so the module graph is populated correctly (`.github/workflows/ci.yml`)

### Fixed
- **Flaky parallel delegation tests**: Replaced wall-clock timing assertions (`elapsed < 0.08 s`) with event-log ordering checks that are robust under CI load (`test_parallel_delegation.py`)

### Added
- **`FailureClass` enum**: six-way failure classification (`PERMANENT_CONFIG`, `PERMANENT_AUTH`, `TRANSIENT_TIMEOUT`, `TRANSIENT_ERROR`, `LOGICAL_ERROR`, `UNKNOWN`) with `is_permanent` property for immediate tool suppression
- **`classify_failure()`**: static method on `ToolCallTracker` — classifies tool errors from `error_type` metadata and keyword context; narrows `"no such"` / `"not found"` matches to command/binary context only to avoid false-positive permanent disabling on file-not-found errors
- **`_build_failure_prompt()`**: replaces static `failure_strategy.md` injection with a dynamic REFLECT-phase prompt built from live tracker state and per-class recovery guidance
- **Turn-scoped tool suppression** (`disabled_tools: set[str]` in `_run_agent_loop`): tools that hit the failure threshold or classify as permanently failed are excluded from the LLM's tool list for the current turn only; the registry is never mutated, so suppressed tools become available again in subsequent turns (fixes permanent tool removal regression)
- **Background missions**: `MissionManager` + `MissionStartTool` / `MissionStatusTool` / `MissionListTool` / `MissionCancelTool` for asynchronous delegated task execution with coordinator routing, structured contracts, task taxonomy, grounding verification, and direct result delivery via `OutboundMessage`
- **Mission observability**: Langfuse spans wrapping mission execution, `score_current_trace` for grounding, `TraceContext` correlation IDs, `update_current_span` for completion metadata, `tool_span` in `run_tool_loop`
- **MCP tool sharing**: MCP tools are now available within background missions and delegated agents (shared `MCPToolWrapper` instances, respecting role-based `denied_tools`/`allowed_tools` filters)
- **`MissionConfig`**: configurable `max_concurrent` (default 3), `max_iterations` (default 15), `result_max_chars` (default 4000) via `config.json` under `agents.defaults.mission`
- **`tool_loop.py`**: extracted shared lightweight think→act→observe loop from deprecated `subagent.py`, used by both `MissionManager` and `DelegationDispatcher`
- **Honest delivery**: `DeliveryResult` dataclass + `DeliverySkippedError` for truthful send confirmation
- **Tool retry guard**: `ToolCallTracker` with 3-level escalation (warn → inject → force-stop) to prevent infinite tool loops
- **Email validation**: `allow_to` allowlist + `proactive_send_policy` config fields; address format validation
- **Email checking tool**: `CheckEmailTool` for on-demand mailbox reading via IMAP (periods: unread, today, yesterday, last_N_days, custom date ranges); wired via callback pattern respecting module boundaries
- **Compression coherence**: paired-drop logic (`_paired_drop_tools`) preserves tool-call/result pairs during context truncation
- **Delegation verification**: `DelegationResult` attestation, scratchpad grounded tags, post-delegation nudge for ungrounded results
- **Langfuse hardening**: `atexit` shutdown safety net, `auth_check()` on startup, `sample_rate`/`debug` config fields, verification confidence scoring via `score_current_trace`, session/user/tag propagation on all traces, logging filters for benign litellm/langfuse/OTEL warnings
- **Langfuse tracing reliability**: crash-barrier log levels elevated from DEBUG to WARNING for visibility; `reset_trace_context()` clears stale OTEL spans between bus-loop iterations; explicit `flush_langfuse()` after each Telegram request; `tracing_health()` counters for diagnostics; `hasattr` guard on litellm monkey-patch; timeout handler moved inside trace scope
- **CI enforcement**: import-boundary check, prompt-manifest integrity, coverage gate (85%)
- **CODEOWNERS**: code review ownership for all major subsystems
- **Contract tests**: LLMProvider, MemoryStore, and BaseChannel compliance suites
- **Golden test expansion**: tool failure recovery, planning injection, parallel readonly scenarios
- **Workflow E2E tests**: full pipeline, context assembly, error handling, memory roundtrip, multi-turn
- **Prompt regression tests**: asset existence, loader verification, key phrase checks
- **Telemetry**: request audit line with timing, structured tool execution logs, `record_request()` metric helper
- **LogConfig**: `log.level`, `log.json_stdout`, `log.json_file` configuration for structured logging
- **Operating policies doc**: canonical reference for runtime defaults and safety boundaries
- **Prompt inventory doc**: template registry with integrity verification and change process
- **Test strategy doc**: 4-layer testing approach (unit, contract, golden, workflow)
- **Branch protection doc**: recommended GitHub settings for main branch
- **Hardening backlog**: prioritised list of reliability and resilience improvements
- **Release checklist**: step-by-step validation process for releases

### Changed
- **`ToolCallTracker.record_failure()`** return type changed from `int` to `tuple[int, FailureClass]` — callers must unpack both values
- **`failure_strategy.md`** is now a design reference only; runtime failure guidance is generated dynamically by `_build_failure_prompt()` from live tracker state
- **Context compression** (`summarize_and_compress`) now guarded by an 85% token-budget threshold — skipped on iterations where messages are well under budget (PERF-C1)
- **`tools_def` list** cached between loop iterations and recomputed only when `disabled_tools` changes (PERF-C2)
- `_run_agent_loop()` tool execution now logs with `bind_trace()` and batch timing
- `_process_message()` emits request-complete audit line with duration and tool count
- Legacy `MetricsCollector` removed — observability now via Langfuse
- Token consumption tracked per-turn via Langfuse span metadata
- `shutdown_langfuse()` called in all CLI `finally` blocks for reliable trace export
- `LangfuseConfig` extended with `sample_rate` (float, default 1.0) and `debug` (bool)
- CI test job now enforces `--cov-fail-under=85`
- `make check` now includes prompt manifest verification

### Removed
- **Channel adapters**: DingTalk, Feishu, Mochat, QQ (unmaintained, no active users)
- **SubagentManager / SpawnTool**: replaced by `MissionManager` + background mission tools (dead code cleanup)

## [0.1.4] - 2025-03-10

Initial tracked release. Core agent framework with:
- Plan-Act-Observe-Reflect agent loop
- 100+ LLM model support via litellm
- 5 channel adapters (Telegram, Discord, Slack, WhatsApp, Email)
- mem0-first memory with local JSONL fallback
- Plugin skill system with auto-discovery
- Multi-agent coordination with intent routing
- Shell, filesystem, web, MCP tool implementations
