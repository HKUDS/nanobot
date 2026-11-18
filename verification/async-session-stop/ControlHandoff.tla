--------------------------- MODULE ControlHandoff ---------------------------
CONSTANT FenceStart
VARIABLES controls, secondUsed, target, other, startedTooSoon

vars == <<controls, secondUsed, target, other, startedTooSoon>>

Init ==
    /\ controls = {"stop"}
    /\ secondUsed = FALSE
    /\ target = "notSubmitted"
    /\ other = "queued"
    /\ startedTooSoon = FALSE

SubmitReplacement ==
    /\ target = "notSubmitted"
    /\ target' = "queued"
    /\ UNCHANGED <<controls, secondUsed, other, startedTooSoon>>

StartNestedControl ==
    /\ ~secondUsed
    /\ controls # {}
    /\ target \in {"notSubmitted", "queued"}
    /\ controls' = controls \cup {"discard"}
    /\ secondUsed' = TRUE
    /\ UNCHANGED <<other, startedTooSoon>>
    /\ target' = IF target = "queued" THEN "cancelled" ELSE target

FinishControl ==
    /\ \E ctl \in controls: controls' = controls \ {ctl}
    /\ UNCHANGED <<secondUsed, target, other, startedTooSoon>>

StartReplacement ==
    /\ target = "queued"
    /\ ~FenceStart \/ controls = {}
    /\ target' = "started"
    /\ startedTooSoon' = (controls # {})
    /\ UNCHANGED <<controls, secondUsed, other>>

FinishAnotherSession ==
    /\ other = "queued"
    /\ other' = "done"
    /\ UNCHANGED <<controls, secondUsed, target, startedTooSoon>>

Next == SubmitReplacement \/ StartNestedControl \/ FinishControl \/ StartReplacement \/ FinishAnotherSession
Spec ==
    /\ Init
    /\ [][Next]_vars
    /\ WF_vars(FinishControl)
    /\ WF_vars(StartReplacement)
    /\ WF_vars(FinishAnotherSession)
NoStartDuringOldCleanup == ~startedTooSoon
OtherSessionStillRunnable == other = "queued" => ENABLED FinishAnotherSession
ReplacementStartsOrCancels == (target = "queued") ~> (target \in {"started", "cancelled"})
=============================================================================
