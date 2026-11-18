# Attach reconciliation: bounded verification

A disconnect can drop the only named terminal observation. Even if the socket reconnects, paged history may fail or omit that ID. The attach reply therefore reports **all live named owners for the attached chat**. It is an absence check for previously confirmed, still-open owners marked by transport loss, not a new source of ownership, transcript coverage, or completion events. This is a separate finite model from the history/cache partitions; it is not a checked refinement of the Gateway or TypeScript.

## Source boundary and checked behavior

| Boundary | `AttachReconciliation.tla` |
| --- | --- |
| `nanobot/webui/inbound_commands.py` trusted `attach`, metadata in `session_projection.py`, WebSocket writer in `nanobot/channels/websocket/runtime.py` | `Subscribe` precedes the asynchronous metadata wait; `EnqueueAttached` samples `Live` and enqueues in one step on the same FIFO as pushes. `Hydrate` is separate ordinary running evidence. |
| `nanobot/session/webui_turns.py` delivery owners and `nanobot/webui/outbound_delivery.py` terminal/idle delivery | The named owner stays live while terminal persistence is in flight. Retirement removes it from live status for either persistence outcome; an incomplete transcript can remain without being reported as running by attach, hydration, or the session list. Named idle also retires the owner. `LateRecipients` selects TurnEnd recipients after persistence, not before it. |
| `webui/src/lib/nanobot-client.ts` socket replacement and `client-run-ledger.ts` ownership | `LoseTransport` marks only confirmed open names, including neither queued local work nor anonymous recovery. `Observe` closes and tombstones marked absent IDs; presence alone adds no owner. Ordinary running hydration/push can create one. `ReceiveOld` ignores a previous socket's callback, and `ReplayBuffered` checks that a delayed start/delta cannot reopen a tombstoned lifecycle. |
| Paged HTTP recovery (`useReconnectRuns.ts` and the history models) | One independent optional attempt fails or returns a fragment without the needed ID. Neither supplies lifecycle evidence here; a successful page exposing an explicit ID is verified in the separate history partitions. |

`TypeOK` and `LifecycleSafety` check that no live name is closed; the exact marked/open absent IDs are closed and tombstoned without adding owners, clearing a surviving clock, changing independent anonymous/queued work, fencing content, or generating synthetic completion. Server turn 1 starts at a reachable checkpoint (confirmed on the old connection, with a potentially lagging duplicate running event). Turn 2 can start while turn 1's terminal projection is awaiting persistence or after it retires. Consequently a sample may contain both names, preserve a still-running name, report a newer name not yet observed, or omit an old name while the newer one is already open. An independent queued candidate can be present at the loss or submitted after it. One or two drops may occur, including during handshake or before writer delivery.

`EventuallyRetiredOwnersSettle` checks each name independently: if the socket stays healthy after reconnect and that named owner is retired, eventually the client has no open ownership for that name and never reopens it. A newly queued send, anonymous recovery, or a different still-running server turn need not settle for this to hold. If none of those independent activities remain, settlement removes the stale busy indicator. The ordering argument is that a retirement **before** the sample yields absence; a retirement **after** the sample still addresses the already-subscribed socket. A later loss marks again and requires a later healthy attach.

## Scope and fairness

The model checks one chat, two unique named server IDs and one independent unacknowledged local candidate, one callback slot from a previous socket, and one late lifecycle replay probe. There is one complete, trusted snapshot per reconnect; retaining a mark for a live name after that snapshot is immaterial because the next loss recomputes marks. The queue models current-socket enqueue and receive order, not transcript or send-queue internals. Terminal recipient selection, retirement and enqueue are one model step after persistence; named idle is modeled without a persistence gap. Current-socket running hydration samples and enqueues in one step; the model does not cover an older server-side hydration task publishing a stale status onto a replacement socket. The wire does not independently discard addressed frames while healthy. Matching, writer serialization and lifetime/ownership hooks in the implementation require separate source review and regression tests.

Weak fairness is for reconnect, subscribe, completing the metadata wait and enqueuing `attached`, ordinary hydration and processing a nonempty healthy writer. It permits finite delay or another loss at any point. No fairness is assumed for turn admission or completion, local/anonymous work, HTTP, stale callbacks, or another disconnect. Permanent outage, a reconnect with no subsequent healthy synchronization, malformed or missing attach evidence, authentication/host changes, unbounded workloads, cross-chat interactions, and transcript/text projection are outside this liveness claim. There is no state constraint, symmetry reduction, or depth cutoff. Terminal states can stutter (`CHECK_DEADLOCK FALSE`).

## Reproduce and evidence

Use `python3 -B webui/verification/turn-sync/run_tlc.py --jar /path/to/verified-tla2tools.jar --case <config>` from the repository root, repeating `--case` to select multiple cases. The three fixed cases are in the default positive suite. `--limits` runs both attach baselines and the two older history-only baselines, not any positive checks.

Reference run with TLC 2.19, two workers, using the checked TLA+ 1.7.4 jar (SHA-256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`):

| Config | Client absence / late recipients | History | Loss bound | Generated / distinct / queued | TLC exit |
| --- | --- | --- | ---: | ---: | ---: |
| `attach-fixed-failed-read` | on / on | fail | 1 | 307,427 / 71,020 / 0 | 0 |
| `attach-fixed-fragment-id` | on / on | omitted ID | 1 | 307,427 / 71,020 / 0 | 0 |
| `attach-fixed-repeated-loss` | on / on | fail | 2 | 1,463,131 / 308,796 / 0 | 0 |
| `attach-baseline-no-reconciliation` | off / on | fail | 1 | 288,335 / 68,452 / 0 | 13 |
| `attach-baseline-early-recipients` | on / off | fail | 1 | 376,255 / 84,676 / 0 | 13 |

The first baseline drops turn 1's terminal/idle before subscribing and ignores the later absence. The second begins terminal persistence before the new subscription, includes turn 1 as live in `attached`, and then omits the new socket when fanout uses the old recipient set. In both traces turn 1 stays open after retirement and after the healthy writer drains. Exit 13 is an expected temporal counterexample (`LIMITATION_COUNTEREXAMPLE`), not a passing liveness check; counts for negative searches can depend on search order.
