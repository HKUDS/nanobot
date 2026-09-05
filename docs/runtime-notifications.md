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

Subscriptions bind the handler parameter to its event type at the static API.
Catch-all handlers must accept the complete runtime event union. Disconnect is
idempotent and prevents callbacks that have not started, including callbacks in
an existing dispatch snapshot; it does not cancel a handler already executing.

`publish` is an awaited connection: a slow handler delays the caller. Persistence
and state transitions use this path deliberately. `publish_nowait` schedules the
same ordered dispatch and returns its task; the bus retains the task until it
finishes. It is not a per-subscriber worker queue. Gateway shutdown stops producers,
closes runtime resources, drains scheduled dispatches, then exits the coordinator
connection scope. Optional telemetry that needs independent throughput should use
an explicitly owned, bounded worker; it must not be silently mixed into durability
handlers. No such worker is needed by the current notification consumers.

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
boundary adapters. Provider retry entry points adapt the default notification
sink before dispatching to a single provider or fallback chain; loop and runner
carry no retry-specific callback. Explicit provider callbacks take precedence,
including candidate-exhaustion capture inside a fallback chain.
Retry policy still decides when a wait or exhaustion notice is
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

## Other internal notification paths

| Path | Classification | Boundary that must survive a migration |
| --- | --- | --- |
| Compaction and retry wait | Use the scoped sink | Stable compaction identity, cancellation terminal, candidate versus chain exhaustion |
| Fallback model selection | Notification candidate | The successful model, admitted preset, and originating run must be captured together; the current gateway-installed observer reads request context |
| Tool/file-edit progress and reasoning | Notification candidates | `AgentProgressHook` and `FileEditActivityHook` probe callback signatures; a typed event boundary can replace that probing, but custom progress callbacks still need capability-aware adaptation |
| SDK runtime admission | Notification candidate | SDK `run_started` precedes stream output and also covers commands that do not admit a model runtime; subscribing only to `TurnRuntimeAdmitted` would lose that fallback |
| Turn/run/model/goal state | Already runtime events | Coordinator ordering, session ownership, and persistence remain authoritative; a second envelope would only duplicate the existing contract |
| Token streaming and stream recovery | Data flow and control, not only notification | SDK bounded queues, stream segment IDs, backpressure, and retry-after-partial-output guards must remain coupled to the operation |
| Checkpoints, message injection, consolidation, continuation, content-finalization hooks | Calls with results or completion requirements | The runner consumes their return values or waits for durable completion; dropping a listener cannot mean success |

The next useful notification cut is fallback-model selection: replace the shared
provider's gateway-specific observer with a scoped domain event, then project it
using the admitted runtime. A model-only event without the preset and originating
run is insufficient. File-edit progress should migrate together with its callback
capability adaptation, not gain a second output path beside `on_progress`.

## Design reference

[Qt signals and slots](https://doc.qt.io/qt-6/signalsandslots.html) inform the
handler/type pairing and connection-lifetime boundary. Gateway uses a lexical
connection scope rather than object destruction. Awaited and scheduled dispatch
are explicit, without importing Qt or adding automatic thread-affinity rules.

[LangGraph custom streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
separates operation-generated progress from consumers through an execution-scoped
writer. This design adopts that separation with explicit dependency injection,
while retaining nanobot's existing queue, WebSocket protocol, and persistence
owners. It does not introduce a graph runtime or a new transport.
