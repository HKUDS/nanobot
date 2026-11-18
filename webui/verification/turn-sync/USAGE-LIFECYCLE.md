# Full-page lifecycle observation: bounded verification

These are handwritten, source-aligned finite abstractions, **not checked TypeScript refinements or an all-system/compositional liveness theorem**. Run `run_tlc.py --implementation-root <repository-root>` to record the actual source snapshot. Review models and source mapping together when implementation changes.

## Current source mapping

`useReconnectRuns` computes pure cache eligibility, publishes an eligible cache, then unconditionally calls `settleCompletedRunLifecycle` for a fresh, nonaborted full page. Explicit IDs do not authorize whole-snapshot adoption, content fencing or anonymous-recovery clearing. Only an unmounted, eligible, idle response gets background canonical adoption. Mounted transcripts remain the sole mounted whole-snapshot actor. Fragment handoff is separate.

| Source anchor | Abstraction |
| --- | --- |
| `useReconnectRuns`: unsettled-chat jobs, captured generation/turn, post-await abort | `UsageLifecycle.Reconnect`, `NewRead`, disconnected R cancellation and `Process` eligibility |
| Pure preflight before cache publication | `Process.canApply/canCache/cacheInstall` use the pre-transition ledger, before completion settlement |
| Fresh full-page explicit lifecycle settlement | `Process.lifecycle` applies even with an owner and rejected cache admission |
| Idle-only unmounted whole-snapshot adoption | `ownerWhole` versus `backgroundWhole`; never both |
| `useNanobotStream`: own-read/non-seed cache handoff versus exposed fragment IDs | `ownerWhole`, separate `accepted` and `exposed`; no fragment-gap bridging proof |
| Owner/disposal/supersession guards and synchronous cache install | `mounted` separate from `selected`, canceled H after publication, `CacheHandoff.ownReadSuperseded/owner` |
| `ClientRunLedger.completeTurns` | Exact named `open/closed/clock` settlement; content coverage alone extends `fenced`; lifecycle coverage preserves anonymous recovery |

`ClientRunLedger` owns observed client run state. `completeTurns` unifies explicit canonical completed-ID closure, not every supported completion transition. Live terminal observations and legacy observed-turn settlement retain their own supported transitions; `UsageLifecycle.Receive` is separate. The Gateway remains execution authority.

Cache publication and its synchronous owner callback are one model action; navigation cannot interleave within it. The resulting ledger combines authorized owner content closure with idempotent reconnect lifecycle closure. This is not an instruction-by-instruction proof of callback reentrancy or notification ordering.

## Dynamic lifecycle and handoff cases

| Config | Module | Expected result | Reference distinct states |
| --- | --- | --- | ---: |
| `lifecycle-fullpage-dynamic` | `UsageLifecycle.tla` | exit 0, no error, queue 0 | 114,597 |
| `handoff-fullpage-active` | `CacheHandoff.tla` | exit 0, no error, queue 0 | 80 |
| `handoff-fullpage-idle` | `CacheHandoff.tla` | exit 0, no error, queue 0 | 80 |

The dynamic case has one chat, two sequential server turns, two outages and two selection changes, starting unselected. Selected and actually mounted owners are separate: a scheduled refresh may remain pending until selection away. Mounted-history H and reconnect R capture/processing are separate. The workload includes pending/active metadata, stale generations, transcript admission choices and independent anonymous activity. Full pages contain all bounded persisted completion IDs. Read failures and fragments are excluded from this positive workload, not hidden by fairness or state constraints.

The config checks `TypeOK`, `NoOlderCompletionClearsNewer`, `PartialCompletionPreservesRecovery`, `LifecycleOnlyPreservesContentAndRecovery`, `ActiveUnmountedSnapshotIsNotAdopted`, `CachePrecedesIdleNotification`, `SoleCanonicalActor` and `ExplicitCompletionHandoffSettles`. It checks `RawExplicitCompletionsSettle` and `EventuallyIdle` in the same run. Raw learning includes every processed full-page ID even when cache admission fails: `learned ∩ open = {}`.

The conditional temporal property is:

```tla
Quiescent == connected /\ (\A c \in Chats : Done(c) = Turns /\ ~ledger[c].anonymous)
EventuallyIdle == [] (Quiescent => <>[] (\A c \in Chats : ~Active(c)))
```

Weak fairness covers reconnect, an already-scheduled hook effect, existing wire delivery and capture/processing of an already-started read. There is no fairness for starting/finishing future server turns, ending anonymous recovery, retries, fragment bridging or creation of later session-update reads. There is no state/action constraint, symmetry reduction or depth cutoff.

The handoff cases start at a source-reachable checkpoint: observed turn 1, lost terminal, fresh shared R/H read completing 1 and either active/pending 2 or an idle tail. They cover both transcript admission outcomes, two switches, canceled/superseded own callbacks, raw settlement, liveness, sole canonical actor and an unsettled other-chat sentinel. They check eligible handoff ownership, not the entire dynamic graph or transcript text projection.

The maintained actual-hooks regression exercises the deferred-refresh boundary: a mounted reconnect full page completes 1 while 2 is still open; preflight rejects content adoption; selection away cancels the pending history refresh. Lifecycle observation closes only 1, preserving 2's owner/clock and uncovered content. Ending 2 can then leave idle without another refresh. This concrete regression and the model graph are separate forms of verification.

## Current-policy limits

`--limits` runs two cases separately from positive checks. Each must retain exit 13 and the temporal-property violation signature. Their runner status is `LIMITATION_COUNTEREXAMPLE`, not a passing liveness result; reached-state counts depend on concurrent search order.

- `lifecycle-failed-read-limit` allows needed reads to fail. A lost terminal plus failed recovery can leave an owner unresolved; fairness cannot manufacture a later retry.
- `lifecycle-fragment-id-limit` allows fragments with omitted completion IDs and no switches. Without an owner/bridge/future read, completion evidence may never arrive. This is not an assertion about a particular native Gateway payload.
- Larger current-policy two-chat products remain optional and are not claimed exhausted. Separate request/ledger/lifecycle graphs and other-chat sentinels are not a checked compositional liveness theorem.

H/R captures overapproximate independent producers; concrete request sharing/abort is a separate `SharedRequests` partition. Transcript fragment joining, token/auth/client replacement, backend execution, eviction, multiple tabs/hosts, send queues and unbounded workloads are outside this model. Logs, states, source snapshots and the jar stay outside the checkout.
