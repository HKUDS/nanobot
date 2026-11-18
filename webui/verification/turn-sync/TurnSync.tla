----------------------------- MODULE TurnSync -----------------------------
EXTENDS Naturals, FiniteSets, Sequences

\* Shared server, wire and ledger state for the fixed-mount model.
CONSTANTS A, B, Mounted

Turns == {A, B}
None == "none"
Frames == [kind : {"running", "end"}, turn : Turns]

VARIABLES server, connected, disconnected, wire,
          open, closed, fenced, latest, clock, generation,
          anonymous, recoverySeen,
          readPhase, requestTurn, requestGeneration,
          snapshotCompleted, snapshotActive, snapshotObserved, snapshotPending,
          learned, collateral, partialRecoveryPreserved, lastAction

vars == <<server, connected, disconnected, wire,
          open, closed, fenced, latest, clock, generation,
          anonymous, recoverySeen,
          readPhase, requestTurn, requestGeneration,
          snapshotCompleted, snapshotActive, snapshotObserved, snapshotPending,
          learned, collateral, partialRecoveryPreserved, lastAction>>

Active == open # {} \/ clock # None \/ anonymous

Init ==
    /\ server = [t \in Turns |-> "new"]
    /\ connected = TRUE
    /\ disconnected = FALSE
    /\ wire = <<>>
    /\ open = {}
    /\ closed = {}
    /\ fenced = {}
    /\ latest = None
    /\ clock = None
    /\ generation = 0
    /\ anonymous = FALSE
    /\ recoverySeen = FALSE
    /\ readPhase = "none"
    /\ requestTurn = None
    /\ requestGeneration = 0
    /\ snapshotCompleted = {}
    /\ snapshotActive = None
    /\ snapshotObserved = {}
    /\ snapshotPending = FALSE
    /\ learned = {}
    /\ collateral = {}
    /\ partialRecoveryPreserved = TRUE
    /\ lastAction = "init"

Enqueue(kind, t) ==
    IF connected THEN Append(wire, [kind |-> kind, turn |-> t]) ELSE wire

Start(t) ==
    /\ server[t] = "new"
    /\ t = A \/ server[A] = "done"
    /\ server' = [server EXCEPT ![t] = "running"]
    /\ wire' = Enqueue("running", t)
    /\ lastAction' = IF t = A THEN "server-start-A" ELSE "server-start-B"
    /\ UNCHANGED <<connected, disconnected, open, closed, fenced, latest, clock,
                   generation, anonymous, recoverySeen, readPhase, requestTurn,
                   requestGeneration, snapshotCompleted, snapshotActive,
                   snapshotObserved, snapshotPending, learned, collateral, partialRecoveryPreserved>>

Finish(t) ==
    /\ server[t] = "running"
    /\ server' = [server EXCEPT ![t] = "done"]
    /\ wire' = Enqueue("end", t)
    /\ lastAction' = IF t = A THEN "server-finish-A" ELSE "server-finish-B"
    /\ UNCHANGED <<connected, disconnected, open, closed, fenced, latest, clock,
                   generation, anonymous, recoverySeen, readPhase, requestTurn,
                   requestGeneration, snapshotCompleted, snapshotActive,
                   snapshotObserved, snapshotPending, learned, collateral, partialRecoveryPreserved>>

Disconnect ==
    /\ connected /\ ~disconnected
    /\ connected' = FALSE
    /\ disconnected' = TRUE
    /\ wire' = <<>>
    /\ lastAction' = "disconnect"
    /\ UNCHANGED <<server, open, closed, fenced, latest, clock, generation,
                   anonymous, recoverySeen, readPhase, requestTurn, requestGeneration,
                   snapshotCompleted, snapshotActive, snapshotObserved, snapshotPending, learned,
                   collateral, partialRecoveryPreserved>>

Reconnect ==
    /\ ~connected /\ disconnected
    /\ connected' = TRUE
    /\ wire' = IF server[B] = "running" THEN <<[kind |-> "running", turn |-> B]>>
               ELSE IF server[A] = "running" THEN <<[kind |-> "running", turn |-> A]>>
               ELSE <<>>
    /\ readPhase' = IF Active THEN "requested" ELSE "none"
    /\ requestTurn' = latest
    /\ requestGeneration' = generation
    /\ lastAction' = "reconnect-and-request"
    /\ UNCHANGED <<server, disconnected, open, closed, fenced, latest, clock,
                   generation, anonymous, recoverySeen, snapshotCompleted,
                   snapshotActive, snapshotObserved, snapshotPending, learned, collateral,
                   partialRecoveryPreserved>>

Receive ==
    /\ connected /\ Len(wire) > 0
    /\ LET m == Head(wire)
           ignored == m.turn \in fenced \/ (m.kind = "running" /\ m.turn \in closed)
       IN /\ wire' = Tail(wire)
          /\ IF ignored
                THEN UNCHANGED <<open, closed, latest, clock, generation, anonymous>>
                ELSE IF m.kind = "running"
                     THEN /\ open' = open \cup {m.turn}
                          /\ latest' = m.turn
                          /\ clock' = m.turn
                          /\ generation' = generation + 1
                          /\ anonymous' = FALSE
                          /\ UNCHANGED closed
                     ELSE /\ open' = open \ {m.turn}
                          /\ closed' = closed \cup {m.turn}
                          /\ clock' = IF latest = None \/ latest = m.turn THEN None ELSE clock
                          /\ anonymous' = IF latest = None \/ latest = m.turn THEN FALSE ELSE anonymous
                          /\ UNCHANGED <<latest, generation>>
          /\ readPhase' = IF ~ignored /\ m.kind = "end" /\ readPhase \in {"requested", "ready"}
                             THEN "requested" ELSE readPhase
          /\ lastAction' = IF m.kind = "running"
                              THEN IF m.turn = A THEN "receive-running-A" ELSE "receive-running-B"
                              ELSE IF m.turn = A THEN "receive-end-A" ELSE "receive-end-B"
    /\ UNCHANGED <<server, connected, disconnected, fenced, recoverySeen,
                   requestTurn, requestGeneration, snapshotCompleted,
                   snapshotActive, snapshotObserved, snapshotPending, learned, collateral,
                   partialRecoveryPreserved>>

EndAnonymousRecovery ==
    /\ connected /\ anonymous /\ server[B] = "done"
    /\ closed' = closed \cup open \cup (IF latest = None THEN {} ELSE {latest})
    /\ open' = {}
    /\ latest' = None
    /\ clock' = None
    /\ anonymous' = FALSE
    /\ lastAction' = "end-anonymous-recovery"
    /\ UNCHANGED <<server, connected, disconnected, wire, fenced, generation,
                   recoverySeen, readPhase, requestTurn, requestGeneration,
                   snapshotCompleted, snapshotActive, snapshotObserved, snapshotPending,
                   learned, collateral, partialRecoveryPreserved>>

TypeOK ==
    /\ server \in [Turns -> {"new", "running", "done"}]
    /\ connected \in BOOLEAN /\ disconnected \in BOOLEAN
    /\ \A i \in 1..Len(wire) : wire[i] \in Frames
    /\ open \subseteq Turns /\ closed \subseteq Turns /\ fenced \subseteq Turns
    /\ latest \in Turns \cup {None} /\ clock \in Turns \cup {None}
    /\ generation \in 0..4 /\ requestGeneration \in 0..4
    /\ anonymous \in BOOLEAN /\ recoverySeen \in BOOLEAN
    /\ readPhase \in {"none", "requested", "ready", "handled"}
    /\ requestTurn \in Turns \cup {None}
    /\ snapshotCompleted \subseteq Turns /\ snapshotObserved \subseteq Turns
    /\ snapshotActive \in Turns \cup {None} /\ snapshotPending \in BOOLEAN
    /\ learned \subseteq Turns /\ collateral \subseteq Turns
    /\ partialRecoveryPreserved \in BOOLEAN

ExplicitCompletionsSettle == learned \cap open = {}
NoOlderCompletionClearsNewer == collateral = {}
PartialCompletionPreservesRecovery == partialRecoveryPreserved

Quiescent == server[A] = "done" /\ server[B] = "done" /\ connected /\ ~anonymous
EventuallyIdle == [] (Quiescent => <>[] ~Active)

=============================================================================
