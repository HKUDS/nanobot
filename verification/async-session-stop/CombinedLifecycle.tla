--------------------------- MODULE CombinedLifecycle -------------------------
CONSTANT JoinControls
Keys == {"A", "B"}
VARIABLES phase, workers, controls, controlled, submitted

vars == <<phase, workers, controls, controlled, submitted>>

Init ==
    /\ phase = "open"
    /\ workers = [k \in Keys |-> "running"]
    /\ controls = {}
    /\ controlled = {}
    /\ submitted = {}

BeginControl(k) ==
    /\ phase = "open"
    /\ k \notin controlled
    /\ controls' = controls \cup {k}
    /\ controlled' = controlled \cup {k}
    /\ workers' = [workers EXCEPT ![k] = IF @ = "running" THEN "cancelling" ELSE @]
    /\ UNCHANGED <<phase, submitted>>

FinishControl(k) ==
    /\ k \in controls
    /\ workers[k] \in {"none", "queued"}
    /\ controls' = controls \ {k}
    /\ UNCHANGED <<phase, workers, controlled, submitted>>

SubmitReplacement(k) ==
    /\ phase = "open"
    /\ workers[k] = "none"
    /\ k \notin submitted
    /\ workers' = [workers EXCEPT ![k] = "queued"]
    /\ submitted' = submitted \cup {k}
    /\ UNCHANGED <<phase, controls, controlled>>

StartReplacement(k) ==
    /\ workers[k] = "queued"
    /\ k \notin controls
    /\ workers' = [workers EXCEPT ![k] = "running"]
    /\ UNCHANGED <<phase, controls, controlled, submitted>>

FinishWorker(k) ==
    /\ workers[k] \in {"running", "cancelling"}
    /\ workers' = [workers EXCEPT ![k] = "none"]
    /\ UNCHANGED <<phase, controls, controlled, submitted>>

BeginClose ==
    /\ phase = "open"
    /\ phase' = "closing"
    /\ workers' = [k \in Keys |-> IF workers[k] = "none" THEN "none" ELSE "cancelling"]
    /\ UNCHANGED <<controls, controlled, submitted>>

TearDown ==
    /\ phase = "closing"
    /\ \A k \in Keys: workers[k] = "none"
    /\ ~JoinControls \/ controls = {}
    /\ phase' = "closed"
    /\ UNCHANGED <<workers, controls, controlled, submitted>>

Next ==
    \/ BeginClose
    \/ TearDown
    \/ \E k \in Keys:
           BeginControl(k) \/ FinishControl(k) \/ SubmitReplacement(k)
           \/ StartReplacement(k) \/ FinishWorker(k)

Spec ==
    /\ Init
    /\ [][Next]_vars
    /\ WF_vars(TearDown)
    /\ \A k \in Keys: WF_vars(FinishControl(k)) /\ WF_vars(FinishWorker(k))

CloseJoinsAllOwners ==
    phase = "closed" => (controls = {} /\ \A k \in Keys: workers[k] = "none")
CloseEventuallyCompletes == (phase = "closing") ~> (phase = "closed")
=============================================================================
