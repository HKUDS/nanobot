# WebUI turn synchronization: bounded TLC models

These models check recovery from a missed terminal frame. History can explicitly complete an older turn without stopping a newer one or discarding uncovered content. Independently, trusted attach can retire a previously confirmed owner absent from the Gateway's complete live-ID set, even if paged history supplies no completion ID.

**These are handwritten abstractions of selected transitions, not mechanical verification of implementation code or proof of all WebUI/Gateway behavior.** The runner checks thirteen configurations by default.

## Files and source mapping

| Model | Current implementation boundary |
| --- | --- |
| `TurnSync.tla` | Shared server, wire, ledger state and live terminal transitions for the fixed-mount submodel; it has no standalone configuration or alternative completion policy. |
| `RevisedTurnSync.tla` | Fixed mounted/unmounted full-page and fragment completion, content/lifecycle coverage, independent anonymous recovery and cache-before-notification ordering. |
| `UsageLifecycle.tla` | Dynamic selection, actual mounted ownership, deferred hook effects and unconditional fresh full-page lifecycle observation. |
| `CacheHandoff.tla` | Shared full-page publication, superseded own reads, one mounted whole-snapshot adopter and rejected stale callbacks. |
| `SharedRequests.tla` | Per-key request sharing, consumer cancellation, invalidation/replacement, reconnect and stale/late delivery. |
| `CompletionAuthority.tla` | Exact-ID ledger closure, coverage-dependent content fencing, anonymous recovery and another-chat isolation. |
| `AttachReconciliation.tla` | Trusted attach snapshot and terminal fanout ordering; loss-marked ownership, stale socket callbacks and lifecycle-only absence reconciliation independent of paged history. |

The runner can record the relevant client and Gateway source hashes; the mapping still requires human review. [`USAGE-LIFECYCLE.md`](USAGE-LIFECYCLE.md) details the dynamic full-page mapping. [`ATTACH-RECONCILIATION.md`](ATTACH-RECONCILIATION.md) describes the separate attach model, fairness assumptions, and reference runs.

The Gateway owns execution. The request registry owns cancellation and stale-response eligibility; `ThreadTranscript` owns content admission/coverage; `ClientRunLedger` alone owns the client's observed run state. Fresh full pages supply explicit completion facts even when mount/cache eligibility prevents content adoption. Eligible history is cached before completion notifications. The mounted transcript alone adopts whole snapshots; only an unmounted reader can perform background adoption, and only for an eligible idle page. Lifecycle-only closure preserves uncovered content and independent anonymous recovery. Initial cached seeds are not fresh evidence. Mounted fragments hand off completed IDs only when their gap/admission rules expose them.

## Checked properties

- `ExplicitCompletionsSettle` / `RawExplicitCompletionsSettle`: learned explicit IDs retain no open lifecycle ownership. Raw full-page learning is independent of content eligibility.
- `NoOlderCompletionClearsNewer`: completing one ID preserves other owners and their clocks.
- `PartialCompletionPreservesRecovery` and `LifecycleOnlyPreservesContentAndRecovery`: named completion preserves independent anonymous recovery and uncovered content.
- `MountedFragmentRequiresAcceptance`, `ActiveUnmountedSnapshotIsNotAdopted`, `CachePrecedesIdleNotification` and `SoleCanonicalActor`: content admission, notification ordering and single-owner boundaries.
- `EventuallyIdle` and `EventuallyRequestsDrain`: conditional eventual quiescence under the stated finite workload and fairness assumptions.
- `LifecycleSafety` and `EventuallyRetiredOwnersSettle`: after healthy reconnection, retired owners settle without completion evidence from history and without closing live owners.

## History partition scope and limits

The fixed-mount submodel has one chat, two sequential server turns, at most one disconnect/reconnect and one logical latest-history read. `Mounted` is fixed for a run. Request, server capture and response processing are separate actions. Full pages contain all completed/observed IDs within the bounded turns. A real selected page can omit an ID, so this assumption matters. Mounted full-page facts are assumed to reach reconciliation; cache routing and dynamic selection are checked separately.

Pending metadata may omit an active ID. Independent anonymous recovery may begin during either executing turn, but no new recovery starts after both turns finish. Full-page liveness uses weak fairness for reconnection, queued lifecycle delivery, history capture and response processing. It assumes successful full responses and no future work; permanent disconnection, failed reads, omitted IDs and unbridgeable fragments do not satisfy that guarantee. Fragment cases check safety without inventing fragment-bridging fairness. Content is one arbitrary A-or-B probe identity with buffered/late tokens, not text reconstruction or eventual rendering.

The expanded dynamic workload has two sequential turns, two outages and two selection changes with selected/mounted state separated. The request partitions cover two keys without invalidation and one key with invalidation/replacement; each has two outages/switches. Local completion algebra considers either focus chat and another-chat sentinel, including overapproximated ledger inputs. These are separate finite graphs, not one combined graph or a checked compositional theorem. Larger two-chat products remain optional and are not claimed exhausted. There are no TLC state constraints or depth cutoffs.

The maintained `reconnect-real-use.test.tsx` tests exercise the real client/hooks independently of these models, including canceled responses, six-chat recovery and a failed page. Separate production-WebUI/real-Gateway acceptance covered two concurrent chats, six turns, two outages and three switches during outstanding reads. Those are concrete schedules, not an unbounded theorem. Backend execution, transcript joining/text projection, authentication replacement, eviction, multiple tabs/hosts and unbounded workloads remain outside the models.

## Reproduce

Requirements: Python 3.9+, Java and the official [`tla2tools.jar` from TLA+ v1.7.4](https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4). No jar is committed. The reference jar reports `TLC2 Version 2.19` and SHA-256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`; this records observed provenance, not an independently verified release signature.

From this directory in PowerShell:

```powershell
python -B .\run_tlc.py --jar 'C:\path\to\tla2tools.jar'
if ($LASTEXITCODE -ne 0) { throw 'TLC check failed' }
```

Use `--case revised-unmounted-live` (repeatable) for individual cases. `--output-root` must name a new directory outside the checkout; otherwise a private temporary directory is allocated. `--implementation-root <repository-root>` records the relevant source hashes without asserting a checked refinement. Models/configs are copied into the external output directory before Java starts. Logs, state graphs and generated traces stay there. `manifest.json` records input/jar hashes, commands, exit statuses and graph counts. Defaults are two workers, a 1536 MiB heap and a 600-second per-case timeout; cases run sequentially.

A passing case requires exit 0, TLC's no-error completion message and an empty state queue. Counterexamples, timeouts and specification errors fail the runner.

## Reference results

| Config | Checked scope | Distinct states |
| --- | --- | ---: |
| `revised-mounted` | Fixed mounted full pages; safety | 10,299 |
| `revised-unmounted` | Fixed unmounted full pages; safety | 16,844 |
| `revised-mounted-fragments` | Mounted full pages/fragments; safety | 79,117 |
| `revised-unmounted-fragments` | Unmounted full pages/fragments; safety | 105,114 |
| `revised-mounted-live` | Mounted full pages; conditional liveness | 10,299 |
| `revised-unmounted-live` | Unmounted full pages; conditional liveness | 16,844 |
| `requests-two-no-invalidations` | Two keys, shared/canceled/late consumers; request-drain liveness | 473,117 |
| `requests-one` | Per-key invalidation/replacement; request-drain liveness | 17,943 |
| `authority` | Exact-ID closure, coverage, isolation and anonymous preservation | 276,480 |
| `lifecycle-fullpage-dynamic` | Dynamic turns/outages/selection; raw completion safety and conditional liveness | 114,597 |
| `handoff-fullpage-active` | Pending newer turn; shared-page handoff and sole canonical actor | 80 |
| `handoff-fullpage-idle` | Idle shared-page handoff and sole canonical actor | 80 |

See [Attach reconciliation](ATTACH-RECONCILIATION.md#reproduce-and-evidence) for the `attach-reconciliation` config and its graph counts. The larger `requests-two` and `lifecycle-fullpage-two-chats` configurations are optional; they are not part of the reference run.
