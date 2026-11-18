-------------------------- MODULE AsyncSessionStop --------------------------
CONSTANT DropCurrentQueue
VARIABLES phase, inbox, job, staleRemoval

vars == <<phase, inbox, job, staleRemoval>>

Init ==
    /\ phase = "beforeStop"
    /\ inbox = "old"
    /\ job = "notSubmitted"
    /\ staleRemoval = FALSE

RequestStop ==
    /\ phase = "beforeStop"
    /\ phase' = "waitingForOldWorker"
    /\ UNCHANGED <<inbox, job, staleRemoval>>

SubmitAutomation ==
    /\ phase # "beforeStop"
    /\ job = "notSubmitted"
    /\ IF inbox = "old"
          THEN /\ job' = "deferred"
               /\ UNCHANGED inbox
          ELSE /\ job' = "queued"
               /\ inbox' = "new"
    /\ UNCHANGED <<phase, staleRemoval>>


FinishOldWorker ==
    /\ phase = "waitingForOldWorker"
    /\ phase' = "cleaningOtherResources"
    /\ inbox' = "none"
    /\ job' = IF job = "deferred" THEN "cancelled" ELSE job
    /\ UNCHANGED staleRemoval

ReturnStop ==
    /\ phase = "cleaningOtherResources"
    /\ phase' = "returned"
    /\ inbox' = IF DropCurrentQueue THEN "none" ELSE inbox
    /\ staleRemoval' = (DropCurrentQueue /\ inbox = "new")
    /\ UNCHANGED job

StartAutomation ==
    /\ inbox = "new"
    /\ job = "queued"
    /\ job' = "running"
    /\ UNCHANGED <<phase, inbox, staleRemoval>>

ExitDetachedWorker ==
    /\ inbox = "none"
    /\ job = "queued"
    /\ job' = "waitingWithoutWorker"
    /\ UNCHANGED <<phase, inbox, staleRemoval>>

FinishAutomation ==
    /\ job = "running"
    /\ job' = "finished"
    /\ inbox' = "none"
    /\ UNCHANGED <<phase, staleRemoval>>

Next ==
    \/ RequestStop
    \/ SubmitAutomation
    \/ FinishOldWorker
    \/ ReturnStop
    \/ StartAutomation
    \/ ExitDetachedWorker
    \/ FinishAutomation

Spec ==
    /\ Init
    /\ [][Next]_vars
    /\ WF_vars(FinishOldWorker)
    /\ WF_vars(ReturnStop)
    /\ WF_vars(StartAutomation)
    /\ WF_vars(ExitDetachedWorker)
    /\ WF_vars(FinishAutomation)

NoStaleRemoval == ~staleRemoval
Settled == job \in {"cancelled", "finished"}
Accepted == job # "notSubmitted"
EveryAcceptedAutomationSettles == Accepted ~> Settled
=============================================================================
