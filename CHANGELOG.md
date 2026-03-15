# Changelog

All notable changes to Nanobot are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Honest delivery**: `DeliveryResult` dataclass + `DeliverySkippedError` for truthful send confirmation
- **Tool retry guard**: `ToolCallTracker` with 3-level escalation (warn → inject → force-stop) to prevent infinite tool loops
- **Email validation**: `allow_to` allowlist + `proactive_send_policy` config fields; address format validation
- **Compression coherence**: paired-drop logic (`_paired_drop_tools`) preserves tool-call/result pairs during context truncation
- **Delegation verification**: `DelegationResult` attestation, scratchpad grounded tags, post-delegation nudge for ungrounded results
- **Langfuse hardening**: `atexit` shutdown safety net, `auth_check()` on startup, `sample_rate`/`debug` config fields, verification confidence scoring via `score_current_trace`, session/user/tag propagation on all traces, logging filters for benign litellm/langfuse/OTEL warnings
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

## [0.1.4] - 2025-03-10

Initial tracked release. Core agent framework with:
- Plan-Act-Observe-Reflect agent loop
- 100+ LLM model support via litellm
- 5 channel adapters (Telegram, Discord, Slack, WhatsApp, Email)
- mem0-first memory with local JSONL fallback
- Plugin skill system with auto-discovery
- Multi-agent coordination with intent routing
- Shell, filesystem, web, MCP tool implementations
