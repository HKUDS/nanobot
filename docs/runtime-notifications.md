# Runtime notifications

Agent operations publish typed notifications through an injected `EventSink`.
The sink carries no WebSocket, channel, session-store, or UI dependency. It is
bound when an operation starts, not looked up from the currently active chat.

```text
operation / context governor / provider
             │ EventSink.emit(AgentEvent)
             ▼
       bound delivery scope
         ├─ audience policy → existing outbound queue → channel projector
         └─ NotificationPublished → in-process observers
```

## Ownership

- `nanobot/events.py` owns transport-independent notification values and the sink.
- `TurnDelivery.events` snapshots the route and its metadata. Idle compaction
  uses `TurnDeliveryFactory.session_events` without claiming an active turn.
- `AgentRunSpec`, `ModelRequestState`, and `ProviderCallContext` carry the same
  sink. A new provider notification does not need a new callback in the runner.
- `bus/notification_delivery.py` explicitly permits audiences. Unregistered
  events remain internal; registration does not implicitly serialize their fields.
- `webui/outbound_wire.py` owns public notification fields and persistence policy.
  The outbound projector performs transport operations using that policy.
- `packages/client-events/notifications.ts` owns the common client notification
  union, boundary validation, and compaction transition rule. Browser and terminal
  presentation remain independent. Python encoders and TypeScript validation run
  against the same wire fixtures; there is no schema generator or new dependency.

The sink awaits publication, preserving each operation's emission order. Eligible
notifications enter the existing outbound queue before runtime observers run.
Observers must not republish the envelope to the same channel. Observer exceptions
are logged without changing the operation's result; cancellation still propagates.
This is neither a durable event log nor a globally ordered stream across sessions.

## Compatibility and durability

Compaction keeps its existing wire fields, phase values, stable IDs, and terminal
activity persistence even without connected clients. Started events are transient.
Recovery-state notifications remain transient; recovery persistence belongs to the
recovery coordinator. Turn completion and token streaming retain their existing
owners and protocols.

Saved idle routes retain the `_compaction_route` storage key so older gateways can
read them. Only channel routing fields survive in that snapshot; active WebUI turn
owners do not. A unified session changing destination cannot redirect an operation
that already bound its sink.

Existing compaction callback entry points and provider retry-text callbacks remain
boundary adapters. Retry policy still decides when a wait or exhaustion notice is
appropriate. Exhaustion of one candidate must not announce failure while a fallback
can succeed. The sink must not infer retry state from callback text.

Terminal compaction rows cannot regress to a queued start after hydration. The
shared transition rule also rejects duplicate phases and conflicting terminal
updates; each client retains its own row identity, timestamp, and rendering state.

## Adding a notification

1. Define a typed domain value and emit it through the operation's existing sink.
2. Choose its channel audience explicitly. Do not put channel names in the producer.
3. Add an explicit wire projection with sanitized fields and transient or durable
   policy. Persisted activities require their own replay projection; selecting a
   persistence string alone does not implement a new history format.
4. Extend the shared client union and validator, then the relevant client rendering.
5. Add producer, routing, wire-fixture, cancellation, and replay tests as applicable.

The shared source is included in the Docker builder, WebUI freshness checks, and
the native TUI corresponding-source archive. The latter preserves sibling
`tui/` and `packages/client-events/` directories so relative imports still resolve.

## Applying this boundary to model retry status

[PR #5504](https://github.com/HKUDS/nanobot/pull/5504) contains two distinct concerns:
transient retry visibility and durable terminal failure information.

For transient status, a typed retry event can be emitted from the provider's
`ProviderCallContext.events`. It can replace the PR's event-specific callback
plumbing through runner, loop, and delivery, and its separate
`TurnRetryStatusChanged` transport envelope. A runtime subscriber may observe
`NotificationPublished` to retain turn-level state without translating and
republishing the same notification. The wire projection still converts deadlines
to relative delays, and a single shared client definition serves both clients.

The retry policy, sanitized error classification, fallback-chain ownership,
countdown presentation, and terminal failure projection are still required.
Those are feature semantics, not removable transport plumbing. In particular,
terminal failure metadata must describe the actual final outcome, not a stale
candidate exhaustion event. System/background routes must preserve lifecycle
suppression in addition to any interactive-only audience rule.

The extension tests prove that a provider can emit an unfamiliar typed event
without changing runner callbacks, and that internal events require explicit
public admission. They do not constitute a port of the retry feature; its
fallback, clearing, terminal-deduplication, and remote-clock tests remain required
when that feature is rebased onto this boundary.

## Design reference

[LangGraph custom streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
separates operation-generated progress from consumers through an execution-scoped
writer. This design adopts that separation with explicit dependency injection,
while retaining nanobot's existing queue, WebSocket protocol, and persistence
owners. It does not introduce a graph runtime or a new transport.
