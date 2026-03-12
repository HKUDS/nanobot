# ADR-005: Observability Standard

## Status

Accepted

## Date

2026-03-11

## Context

Current observability in Nanobot:

- **Logging**: loguru with unstructured string formatting across all modules.
- **Metrics**: `MetricsCollector` — in-memory counters flushed to `metrics.json` every 60s.
- **Tracing**: None. No correlation IDs, no spans, no distributed tracing.

For a professional agent framework, we need to answer questions like:

- "Which tool call caused this session to exceed the token budget?"
- "What was the latency breakdown for this delegation chain?"
- "How often does memory retrieval fall back from mem0 to local?"

## Decision

### Phase 1 — Structured Logging + Correlation IDs (immediate)

1. **Add correlation IDs** threaded through all operations:
   - `request_id` — unique per inbound message
   - `session_id` — conversation session key
   - `agent_id` — role name for multi-agent delegation

2. **Add structured fields** to key log sites:
   - LLM calls: `model`, `input_tokens`, `output_tokens`, `latency_ms`
   - Tool execution: `tool_name`, `duration_ms`, `success`, `error_type`
   - Memory retrieval: `query`, `results_count`, `source` (mem0/local/reranked)
   - Delegation: `from_role`, `to_role`, `depth`, `latency_ms`

3. **Keep loguru** as the logging backend. Use loguru's `bind()` for structured context
   and `serialize=True` sink option for JSON output when needed.

### Phase 2 — OpenTelemetry (future, separate ADR)

When the need arises for distributed tracing or integration with external observability
platforms (Grafana, Datadog, etc.), introduce OpenTelemetry spans. This is explicitly
deferred to avoid premature complexity.

### MetricsCollector

Retain the existing `MetricsCollector` for in-process counters. It is lightweight and
sufficient for current needs.

## Consequences

### Positive

- Correlation IDs make it possible to trace a request through the full processing chain.
- Structured fields enable log analysis and alerting without a heavy tracing framework.
- No new dependencies required for Phase 1 (loguru already supports structured binding).

### Negative

- Threading correlation IDs requires passing context through function signatures or using
  contextvars (adds complexity to function signatures).
- JSON-serialized logs are less human-readable in development (mitigate with a dev-only
  pretty-print sink).

### Neutral

- MetricsCollector continues flushing to disk — no change.
- OpenTelemetry decision deferred, not rejected.
