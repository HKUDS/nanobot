------------------------- MODULE RevisedTurnSync -------------------------
EXTENDS TurnSync

\* Current fixed-mount completion and content-coverage transitions.
\* TurnSync supplies only the shared server, wire and ledger state.
CONSTANT IncludeFragments

VARIABLES snapshotIsFragment, probeTurn, bufferedProbe, lateProbe,
          probeProtected, contentLost, lifecycleOnlyPreserved,
          mountedFragmentPreserved, activeSnapshotNotAdopted,
          cacheBeforeNotification, cached, effectsOrder

extraVars == <<snapshotIsFragment, probeTurn, bufferedProbe, lateProbe,
               probeProtected, contentLost, lifecycleOnlyPreserved,
               mountedFragmentPreserved, activeSnapshotNotAdopted,
               cacheBeforeNotification, cached, effectsOrder>>
revisedVars == <<vars, extraVars>>

RevisedInit ==
    /\ Init
    /\ snapshotIsFragment = FALSE
    \* One arbitrary content identity is sufficient to test either A or B.
    /\ probeTurn \in Turns
    /\ bufferedProbe = "absent"
    /\ lateProbe = "none"
    /\ probeProtected = FALSE
    /\ contentLost = FALSE
    /\ lifecycleOnlyPreserved = TRUE
    /\ mountedFragmentPreserved = TRUE
    /\ activeSnapshotNotAdopted = TRUE
    /\ cacheBeforeNotification = TRUE
    /\ cached = FALSE
    /\ effectsOrder = <<>>

RevisedCaptureWith(fragment, pending, activeId, completions, observed) ==
    /\ readPhase = "requested" /\ connected
    /\ fragment \in BOOLEAN /\ (fragment => IncludeFragments)
    /\ pending \in BOOLEAN
    /\ pending => (anonymous \/ (\E t \in Turns : server[t] = "running"))
    /\ LET done == {t \in Turns : server[t] = "done"}
           seen == {t \in Turns : server[t] # "new"}
           exactActive == IF server[B] = "running" THEN B
                          ELSE IF server[A] = "running" THEN A ELSE None
       IN /\ activeId \in {None, exactActive}
          /\ IF fragment
                THEN /\ completions \subseteq done
                     /\ observed \subseteq seen
                ELSE /\ completions = done
                     /\ observed = seen
    /\ snapshotIsFragment' = fragment
    /\ snapshotPending' = pending
    /\ snapshotCompleted' = completions
    /\ snapshotObserved' = observed
    /\ snapshotActive' = activeId
    /\ readPhase' = "ready"
    /\ lastAction' = "capture-revised-history"
    /\ UNCHANGED <<server, connected, disconnected, wire, open, closed, fenced,
                   latest, clock, generation, anonymous, recoverySeen, requestTurn,
                   requestGeneration, learned, collateral, partialRecoveryPreserved>>
    /\ UNCHANGED <<probeTurn, bufferedProbe, lateProbe, probeProtected,
                   contentLost, lifecycleOnlyPreserved, mountedFragmentPreserved,
                   activeSnapshotNotAdopted, cacheBeforeNotification, cached, effectsOrder>>

RevisedCapture ==
    \E fragment, pending \in BOOLEAN, activeId \in Turns \cup {None},
       completions, observed \in SUBSET Turns :
        RevisedCaptureWith(fragment, pending, activeId, completions, observed)

\* Recovery may begin during either executing turn with either observed owner.
\* New recovery after both server turns finish is excluded by the
\* no-future-work liveness scope.
RevisedStartAnonymousRecovery ==
    /\ connected /\ latest \in Turns
    /\ (\E t \in Turns : server[t] = "running")
    /\ ~anonymous /\ ~recoverySeen
    /\ anonymous' = TRUE
    /\ recoverySeen' = TRUE
    /\ lastAction' = "receive-revised-anonymous-recovery"
    /\ UNCHANGED <<server, connected, disconnected, wire, open, closed, fenced,
                   latest, clock, generation, readPhase, requestTurn,
                   requestGeneration, snapshotCompleted, snapshotActive,
                   snapshotObserved, snapshotPending, learned, collateral, partialRecoveryPreserved>>
    /\ UNCHANGED extraVars

\* A buffered content token represents a pending delta/message/stream_end,
\* not a lifecycle status. It has already reached the client before this read.
BufferProbe ==
    /\ ~Mounted /\ connected /\ probeTurn \in open
    /\ bufferedProbe = "absent" /\ probeTurn \notin fenced
    /\ bufferedProbe' = "queued"
    /\ lastAction' = "buffer-content-probe"
    /\ UNCHANGED <<server, connected, disconnected, wire, open, closed, fenced,
                   latest, clock, generation, anonymous, recoverySeen, readPhase,
                   requestTurn, requestGeneration, snapshotCompleted, snapshotActive,
                   snapshotObserved, snapshotPending, learned, collateral,
                   partialRecoveryPreserved>>
    /\ UNCHANGED <<snapshotIsFragment, probeTurn, lateProbe, probeProtected,
                   contentLost, lifecycleOnlyPreserved, mountedFragmentPreserved,
                   activeSnapshotNotAdopted, cacheBeforeNotification, cached, effectsOrder>>

\* ClientRunLedger.applyObservation: closed activity/progress is forwarded;
\* fenced activity is dropped. Neither branch can reopen lifecycle ownership.
ReceiveLateProbe ==
    /\ connected /\ probeTurn \in closed /\ lateProbe = "none"
    /\ lateProbe' = IF probeTurn \in fenced THEN "dropped" ELSE "forwarded"
    /\ contentLost' = (contentLost \/ (probeProtected /\ probeTurn \in fenced))
    /\ lastAction' = "receive-late-content-probe"
    /\ UNCHANGED <<server, connected, disconnected, wire, open, closed, fenced,
                   latest, clock, generation, anonymous, recoverySeen, readPhase,
                   requestTurn, requestGeneration, snapshotCompleted, snapshotActive,
                   snapshotObserved, snapshotPending, learned, collateral,
                   partialRecoveryPreserved>>
    /\ UNCHANGED <<snapshotIsFragment, probeTurn, bufferedProbe, probeProtected,
                   lifecycleOnlyPreserved, mountedFragmentPreserved,
                   activeSnapshotNotAdopted, cacheBeforeNotification, cached, effectsOrder>>

\* For full pages, accepted abstracts owner.accept(). For fragments it means
\* the owner has admitted/joined the fragment AND exposed its completed IDs.
\* A staged fragment may return true from owner.accept() with no such handoff;
\* that case takes accepted=FALSE here. No fragment-bridging liveness is assumed.
RevisedProcessWithAcceptance(accepted) ==
    /\ readPhase = "ready" /\ connected
    /\ accepted \in BOOLEAN
    /\ LET completed == snapshotCompleted
           represented == latest # None /\ latest \in completed
           \* Completion IDs are supplied; observed IDs alone cannot settle an
           \* open candidate owner. Preflight is evaluated BEFORE settlement.
           canApply == open \subseteq completed /\
                       (generation = requestGeneration \/ represented)
           explicit == requestTurn # None /\ requestTurn \in completed
           idleSnapshot == ~snapshotPending /\ snapshotActive = None
           canCache == (explicit \/ idleSnapshot) /\
                       (requestTurn = None \/ explicit \/ requestTurn \in snapshotObserved) /\
                       canApply
           fragmentReady == snapshotIsFragment /\ (~Mounted \/ accepted)
           \* Mounted full-page reconciliation is intentionally unchanged:
           \* rejection/partial adoption still calls fenceCanonicalCompletedTurns.
           fullAccept == ~snapshotIsFragment /\
                         (IF Mounted THEN accepted /\ ~snapshotPending /\ canApply
                                     ELSE canCache /\ idleSnapshot)
           lifecyclePath == fragmentReady \/ (~snapshotIsFragment /\ ~Mounted)
           wholeFence == ~snapshotIsFragment /\ (Mounted \/ fullAccept)
           settleIds == lifecyclePath \/ wholeFence
           nextOpen == IF settleIds THEN open \ completed ELSE open
           nextClosed == IF settleIds THEN closed \cup completed ELSE closed
           nextFenced == IF wholeFence THEN fenced \cup completed ELSE fenced
           nextClock == IF fullAccept \/ (settleIds /\ latest \in completed)
                        THEN None ELSE clock
           nextAnonymous == IF fullAccept THEN FALSE ELSE anonymous
           nextBuffered == IF wholeFence /\ probeTurn \in completed /\ bufferedProbe = "queued"
                           THEN "pruned" ELSE bufferedProbe
           lifecycleOnly == lifecyclePath /\ ~wholeFence
           didCache == IF snapshotIsFragment THEN canApply ELSE ~Mounted /\ canCache
           \* Order models synchronous cache publication preceding run-status
           \* callbacks; it is not a second asynchronous HTTP/WS transition.
           order == (IF didCache THEN <<"cache">> ELSE <<>>) \o
                    (IF lifecyclePath THEN <<"lifecycle">> ELSE <<>>) \o
                    (IF wholeFence THEN <<"fence">> ELSE <<>>) \o
                    (IF fullAccept THEN <<"adopt">> ELSE <<>>)
           willNotifyIdle == Active /\ nextOpen = {} /\ nextClock = None /\ ~nextAnonymous
       IN /\ open' = nextOpen
          /\ closed' = nextClosed
          /\ fenced' = nextFenced
          /\ clock' = nextClock
          /\ anonymous' = nextAnonymous
          \* A mounted rejected/staged fragment has not yet handed completion
          \* identities to the ledger. Full pages retain the original invariant.
          /\ learned' = learned \cup (IF ~snapshotIsFragment \/ fragmentReady THEN completed ELSE {})
          /\ collateral' = ((open \ completed) \ nextOpen) \cup
                 (IF latest # None /\ latest \notin completed /\ clock = latest /\ nextClock # clock
                  THEN {latest} ELSE {})
          /\ partialRecoveryPreserved' = (fullAccept \/ ~anonymous \/ nextAnonymous)
          /\ bufferedProbe' = nextBuffered
          /\ contentLost' = (contentLost \/
                 (lifecycleOnly /\ bufferedProbe = "queued" /\ nextBuffered # "queued"))
          /\ probeProtected' = IF wholeFence /\ probeTurn \in completed THEN FALSE
                                ELSE probeProtected \/ (lifecycleOnly /\ probeTurn \in completed)
          /\ lifecycleOnlyPreserved' = (~lifecycleOnly \/
                 (nextFenced = fenced /\ nextBuffered = bufferedProbe /\ nextAnonymous = anonymous))
          /\ mountedFragmentPreserved' = (~(Mounted /\ snapshotIsFragment /\ ~accepted) \/
                 (nextOpen = open /\ nextClosed = closed /\ nextFenced = fenced /\
                  nextClock = clock /\ nextAnonymous = anonymous))
          /\ activeSnapshotNotAdopted' = (Mounted \/ snapshotIsFragment \/ idleSnapshot \/ ~fullAccept)
          /\ cached' = (cached \/ didCache)
          /\ effectsOrder' = order
          /\ cacheBeforeNotification' = (~(~Mounted /\ didCache /\ willNotifyIdle) \/
                                           (Len(order) > 0 /\ Head(order) = "cache"))
    /\ readPhase' = "handled"
    /\ lastAction' = "process-revised-history"
    /\ UNCHANGED <<server, connected, disconnected, wire, latest, generation,
                   recoverySeen, requestTurn, requestGeneration, snapshotCompleted,
                   snapshotActive, snapshotObserved, snapshotPending,
                   snapshotIsFragment, probeTurn, lateProbe>>

RevisedProcess == \E accepted \in BOOLEAN : RevisedProcessWithAcceptance(accepted)

RevisedNext ==
    \/ ((\/ \E t \in Turns : Start(t)
         \/ \E t \in Turns : Finish(t)
         \/ Disconnect \/ Reconnect \/ Receive
         \/ EndAnonymousRecovery)
        /\ UNCHANGED extraVars)
    \/ RevisedStartAnonymousRecovery
    \/ RevisedCapture
    \/ RevisedProcess
    \/ BufferProbe
    \/ ReceiveLateProbe

RevisedSpec == RevisedInit /\ [][RevisedNext]_revisedVars
RevisedFairSpec == RevisedSpec /\ WF_revisedVars(Reconnect /\ UNCHANGED extraVars) /\
                   WF_revisedVars(Receive /\ UNCHANGED extraVars) /\
                   WF_revisedVars(RevisedCapture) /\ WF_revisedVars(RevisedProcess)

RevisedTypeOK ==
    /\ TypeOK
    /\ IncludeFragments \in BOOLEAN /\ snapshotIsFragment \in BOOLEAN
    /\ probeTurn \in Turns
    /\ bufferedProbe \in {"absent", "queued", "pruned"}
    /\ lateProbe \in {"none", "forwarded", "dropped"}
    /\ probeProtected \in BOOLEAN /\ contentLost \in BOOLEAN
    /\ lifecycleOnlyPreserved \in BOOLEAN /\ mountedFragmentPreserved \in BOOLEAN
    /\ activeSnapshotNotAdopted \in BOOLEAN /\ cacheBeforeNotification \in BOOLEAN
    /\ cached \in BOOLEAN
    /\ effectsOrder \in Seq({"cache", "lifecycle", "fence", "adopt"})

LifecycleOnlyPreservesContentAndRecovery == lifecycleOnlyPreserved /\ ~contentLost
MountedFragmentRequiresAcceptance == mountedFragmentPreserved
ActiveUnmountedSnapshotIsNotAdopted == activeSnapshotNotAdopted
CachePrecedesIdleNotification == cacheBeforeNotification

=============================================================================
