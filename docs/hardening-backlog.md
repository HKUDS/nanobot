# Hardening Backlog

> Prioritised list of reliability, resilience, and operational improvements.
> Items are ordered by impact × effort ratio. Check off as completed.

## P0 — Critical Path

- [ ] **Capability registry** (ADR-009): Unified tool/skill/role registration with
  availability checks. Prevents LLM from calling unconfigured tools or delegating to
  nonexistent roles. See [`docs/agent-intelligence-layers.md`](agent-intelligence-layers.md)
  for the full 4-layer plan. Target: `agent/capability.py`, `agent/tools/base.py`.
  Branch: `feature/capability-registry`.

- [ ] **Circuit breaker for LLM providers**: Track consecutive failures per provider,
  trip after N errors, auto-recover after cooldown. Prevents cascading retries when
  a provider is down. Target: `providers/litellm_provider.py`.

- [ ] **Graceful shutdown**: Drain in-flight requests before process exit. The agent
  loop's `run()` should catch `SIGTERM`, stop accepting new messages, await pending
  `_process_message()` calls, flush metrics, then exit. Target: `agent/loop.py`.

- [ ] **Memory consolidation timeout**: Long consolidation passes can block session
  processing. Add `asyncio.wait_for()` with configurable limit (default 30s).
  Target: `agent/consolidation.py`.

## P1 — High Impact

- [ ] **Retry budget per request**: Currently retries are per-LLM-call. Add a
  per-request retry budget (e.g., 3 retries total across planning + acting + reflecting)
  to bound total latency. Target: `agent/loop.py` `_run_agent_loop()`.

- [ ] **Health endpoint for gateway**: Return JSON with per-channel health, memory
  store health, provider reachability, and uptime. Target: `cli/commands.py` gateway.

- [ ] **Structured error codes**: Extend `_user_friendly_error()` to return error
  codes alongside messages, enabling clients to display localised errors.
  Target: `bus/events.py` `OutboundMessage`.

- [ ] **Tool execution timeout enforcement**: Individual tool calls should respect
  `exec.timeout` consistently. MCP tools have `tool_timeout` but shell/filesystem
  tools rely on the subprocess timeout. Unify. Target: `agent/tools/`.

## P2 — Medium Impact

- [ ] **Session size limits**: Prevent unbounded session growth. Add a hard cap on
  session message count (e.g., 500) with automatic archival when hit.
  Target: `session/manager.py`.

- [ ] **Dead letter visibility**: The channel manager has a dead-letter queue but no
  way to inspect or replay failed messages. Add CLI commands: `nanobot dlq list`,
  `nanobot dlq replay`. Target: `channels/manager.py`, `cli/commands.py`.

- [ ] **Provider fallback chain**: When the primary provider is unavailable, try a
  configured fallback provider before returning an error to the user.
  Target: `providers/registry.py`.

- [ ] **Rate limit backoff**: When a provider returns 429, implement exponential
  backoff with jitter rather than immediate retry. Currently the crash-barrier
  catches and returns a user message. Target: `agent/streaming.py`.

## P3 — Operational Improvements

- [ ] **Config validation on startup**: Validate all config values (model exists,
  API keys are set, workspace is writable) before starting the agent loop.
  Fail fast with actionable error messages. Target: `cli/commands.py`.

- [x] **Metrics dashboard**: Legacy `MetricsCollector` removed. Observability
  now captured via Langfuse. Use the Langfuse dashboard for metrics.

- [ ] **Audit log**: Append-only log of all tool executions with timestamps,
  arguments, and results. Separate from conversation logs.
  Target: `agent/tool_executor.py`.

- [ ] **Memory store compaction**: Periodic compaction of `events.jsonl` to remove
  superseded events. Currently grows unbounded.
  Target: `agent/memory/persistence.py`.

## Completed

_Move items here as they are resolved._
