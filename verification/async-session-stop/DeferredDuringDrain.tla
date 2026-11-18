-------------------------- MODULE DeferredDuringDrain -------------------------
CONSTANT RetireBeforeNotify
VARIABLES cleanup, inbox, job

vars == <<cleanup, inbox, job>>

Init ==
    /\ cleanup = "beforeDrain"
    /\ inbox = "old"
    /\ job = "notSubmitted"

DrainAndNotify ==
    /\ cleanup = "beforeDrain"
    /\ cleanup' = "awaitingCompletionSubscriber"
    /\ inbox' = IF RetireBeforeNotify THEN "none" ELSE inbox
    /\ UNCHANGED job

SubmitAutomation ==
    /\ cleanup # "beforeDrain"
    /\ job = "notSubmitted"
    /\ IF inbox = "old"
          THEN /\ job' = "deferredToOld"
               /\ UNCHANGED inbox
          ELSE /\ job' = "queued"
               /\ inbox' = "replacement"
    /\ UNCHANGED cleanup

FinishDrain ==
    /\ cleanup = "awaitingCompletionSubscriber"
    /\ cleanup' = "finished"
    /\ inbox' = IF inbox = "old" THEN "none" ELSE inbox
    /\ UNCHANGED job

RunReplacement ==
    /\ inbox = "replacement"
    /\ job = "queued"
    /\ job' = "finished"
    /\ inbox' = "none"
    /\ UNCHANGED cleanup

Next == DrainAndNotify \/ SubmitAutomation \/ FinishDrain \/ RunReplacement
Spec == Init /\ [][Next]_vars /\ WF_vars(FinishDrain) /\ WF_vars(RunReplacement)
NoOrphanedDeferred == job # "deferredToOld" \/ inbox = "old"
EveryAcceptedAutomationSettles == (job # "notSubmitted") ~> (job = "finished")
=============================================================================
