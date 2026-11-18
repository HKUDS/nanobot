-------------------------- MODULE ShutdownAdmission --------------------------
CONSTANT FenceAdmission
VARIABLES lifecycle, oldJob, incomingJob

vars == <<lifecycle, oldJob, incomingJob>>

Init ==
    /\ lifecycle = "open"
    /\ oldJob = "running"
    /\ incomingJob = "notSubmitted"

BeginClose ==
    /\ lifecycle = "open"
    /\ lifecycle' = "closing"
    /\ oldJob' = "cancelling"
    /\ incomingJob' = IF incomingJob = "queued" THEN "cancelled" ELSE incomingJob

SubmitOtherSession ==
    /\ incomingJob = "notSubmitted"
    /\ incomingJob' = IF FenceAdmission /\ lifecycle # "open" THEN "rejected" ELSE "queued"
    /\ UNCHANGED <<lifecycle, oldJob>>

FinishClose ==
    /\ lifecycle = "closing"
    /\ lifecycle' = "closed"
    /\ oldJob' = "cancelled"
    /\ UNCHANGED incomingJob

Next == BeginClose \/ SubmitOtherSession \/ FinishClose
Spec == Init /\ [][Next]_vars
NoWorkOutsideCloseSnapshot == lifecycle = "open" \/ incomingJob # "queued"
=============================================================================
