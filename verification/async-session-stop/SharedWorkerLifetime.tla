------------------------ MODULE SharedWorkerLifetime -------------------------
CONSTANT TrackUntilExit
VARIABLES worker, registered, close, cancellations

vars == <<worker, registered, close, cancellations>>

Init ==
    /\ worker = "running"
    /\ registered = TRUE
    /\ close = "open"
    /\ cancellations = 0

RequestStop ==
    /\ worker = "running"
    /\ close = "open"
    /\ worker' = "unwinding"
    /\ registered' = TrackUntilExit
    /\ cancellations' = 1
    /\ UNCHANGED close

BeginClose ==
    /\ close = "open"
    /\ close' = IF registered THEN "joiningWorker" ELSE "closingResources"
    /\ worker' = IF worker = "running" THEN "unwinding" ELSE worker
    /\ cancellations' = IF worker = "running" THEN 1 ELSE cancellations
    /\ UNCHANGED registered

WorkerExits ==
    /\ worker = "unwinding"
    /\ worker' = "exited"
    /\ registered' = FALSE
    /\ UNCHANGED <<close, cancellations>>

FinishJoin ==
    /\ close = "joiningWorker"
    /\ worker = "exited"
    /\ close' = "closingResources"
    /\ UNCHANGED <<worker, registered, cancellations>>

Next == RequestStop \/ BeginClose \/ WorkerExits \/ FinishJoin
Spec == Init /\ [][Next]_vars /\ WF_vars(WorkerExits) /\ WF_vars(FinishJoin)
CloseDoesNotRaceWorker == close # "closingResources" \/ worker = "exited"
CloseEventuallyJoins == (close # "open") ~> (close = "closingResources" /\ worker = "exited")
=============================================================================
