# Changelog

All notable changes to Nanobot are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- CI test job now enforces `--cov-fail-under=85`
- `make check` now includes prompt manifest verification

## [0.1.4] - 2025-03-10

Initial tracked release. Core agent framework with:
- Plan-Act-Observe-Reflect agent loop
- 100+ LLM model support via litellm
- 9 channel adapters (Telegram, Discord, Slack, WhatsApp, Email, DingTalk, Feishu, Mochat, QQ)
- mem0-first memory with local JSONL fallback
- Plugin skill system with auto-discovery
- Multi-agent coordination with intent routing
- Shell, filesystem, web, MCP tool implementations
