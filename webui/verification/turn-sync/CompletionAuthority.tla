----------------------- MODULE CompletionAuthority -----------------------
EXTENDS Naturals, FiniteSets
\* Local algebra of ClientRunLedger.completeTurns, not a transcript controller.
\* One arbitrary focus ledger; the other chat is a two-open-turn + anonymous
\* sentinel. The transition's syntactic frame is restricted to focus.
\* Completion fact and requested coverage are inputs; coverage admission is
\* owned by the transcript, exercised separately in CacheHandoff.
Chats == {1,2}
Turns == {1,2}
VARIABLES focus, ledger, original, buffer, originalBuffer, completed, coverage,
          phase, selected, switches, lateTurn, lateForwarded, safe
vars == <<focus, ledger, original, buffer, originalBuffer, completed, coverage,
          phase, selected, switches, lateTurn, lateForwarded, safe>>
Ledgers == {l \in [open : SUBSET Turns, closed : SUBSET Turns,
                  fenced : SUBSET Turns, latest : Turns \cup {0},
                  clock : Turns \cup {0}, anonymous : BOOLEAN] :
              l.fenced \subseteq l.closed /\
              (l.clock # 0 => l.clock = l.latest)}
Init ==
 /\ focus \in Chats
 /\ \E l \in Ledgers : ledger = [c \in Chats |-> IF c = focus THEN l ELSE
       [open |-> Turns, closed |-> {}, fenced |-> {}, latest |-> 2, clock |-> 2, anonymous |-> TRUE]]
 /\ original = ledger
 /\ lateTurn \in Turns
 /\ buffer = [c \in Chats |-> IF c = focus THEN {lateTurn} ELSE Turns]
 /\ originalBuffer = buffer
 /\ completed \in SUBSET Turns /\ coverage \in {"lifecycle","content"}
 /\ phase = 0 /\ selected = 0 /\ switches = 0
 /\ lateForwarded = FALSE
 /\ safe = [explicit |-> TRUE, collateral |-> TRUE, anonymous |-> TRUE,
            isolation |-> TRUE, lifecycle |-> TRUE, closedStatus |-> TRUE]
CompleteTurns ==
 /\ phase = 0
 /\ LET l == ledger[focus]
        nl == [l EXCEPT !.open = @ \ completed, !.closed = @ \cup completed,
                     !.fenced = IF coverage = "content" THEN @ \cup completed ELSE @,
                     !.clock = IF l.latest \in completed THEN 0 ELSE @]
    IN /\ ledger' = [ledger EXCEPT ![focus] = nl]
       /\ buffer' = IF coverage = "content" THEN [buffer EXCEPT ![focus] = @ \ nl.fenced] ELSE buffer
       /\ safe' = [safe EXCEPT
          !.explicit = (completed \cap nl.open = {}),
          !.collateral = ((l.open \ completed) = (nl.open \ completed)) /\
                (l.latest \notin completed => nl.clock = l.clock),
          !.anonymous = (nl.anonymous = l.anonymous),
          !.isolation = (\A c \in Chats \ {focus} : ledger'[c] = ledger[c] /\ buffer'[c] = buffer[c]),
          !.lifecycle = (coverage # "lifecycle" \/ (nl.fenced = l.fenced /\ buffer' = buffer))]
 /\ phase' = 1
 /\ UNCHANGED <<focus, original, originalBuffer, completed, coverage, selected, switches, lateTurn, lateForwarded>>
LateContent ==
 /\ phase = 1
 /\ lateForwarded' = (lateTurn \notin ledger[focus].fenced)
 /\ phase' = 2
 /\ UNCHANGED <<focus, ledger, original, buffer, originalBuffer, completed, coverage,
                selected, switches, lateTurn, safe>>
LateRunning ==
 /\ phase = 2
 /\ LET l == ledger[focus]
        drop == lateTurn \in (l.closed \cup l.fenced)
        nl == IF drop THEN l ELSE [l EXCEPT !.open = @ \cup {lateTurn}, !.latest = lateTurn, !.clock = lateTurn]
    IN /\ ledger' = [ledger EXCEPT ![focus] = nl]
       /\ safe' = [safe EXCEPT !.closedStatus = (lateTurn \in l.closed => nl = l)]
 /\ phase' = 3
 /\ UNCHANGED <<focus, original, buffer, originalBuffer, completed, coverage, selected, switches, lateTurn, lateForwarded>>
Switch(c) ==
 /\ c \in Chats \cup {0} /\ c # selected /\ switches < 2
 /\ selected' = c /\ switches' = switches+1
 /\ UNCHANGED <<focus, ledger, original, buffer, originalBuffer, completed, coverage,
                phase, lateTurn, lateForwarded, safe>>
Next == CompleteTurns \/ LateContent \/ LateRunning \/ (\E c \in Chats \cup {0} : Switch(c))
Spec == Init /\ [][Next]_vars
ExplicitCompletionsSettle == safe.explicit
NoOlderCompletionClearsNewer == safe.collateral
PartialCompletionPreservesRecovery == safe.anonymous
OtherChatUnchanged == safe.isolation
LifecycleOnlyPreservesContentAndRecovery == safe.lifecycle
ClosedRunningCannotReopen == safe.closedStatus
LateLifecycleContentSurvives == phase < 2 \/ coverage # "lifecycle" \/
 (lateTurn \notin original[focus].fenced => lateForwarded)
=============================================================================
