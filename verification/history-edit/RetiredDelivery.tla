-------------------------- MODULE RetiredDelivery --------------------------
EXTENDS Naturals

\* One delayed outbound frame and one HTTP page can be captured independently.
\* Only ownership of the discarded suffix matters; content is a probe bit.
\* HTTP page values: 2 = not captured, 0/1 = snapshot generation, 3 = delivered.
CONSTANT FenceClient
VARIABLES generation, dbOld, viewGen, uiOld, wire, page, connected, outage
vars == <<generation, dbOld, viewGen, uiOld, wire, page, connected, outage>>
Init == /\ generation = 0 /\ dbOld = TRUE /\ viewGen = 0 /\ uiOld = TRUE
        /\ wire = "pending" /\ page = 2 /\ connected = TRUE /\ outage = FALSE
Replace == /\ generation = 0 /\ generation' = 1 /\ dbOld' = FALSE
           /\ UNCHANGED <<viewGen, uiOld, wire, page, connected, outage>>
\* Send's ownership precheck is not atomic with later persistence/delivery.
CheckWire == /\ wire = "pending" /\ wire' = IF generation = 0 THEN "checked" ELSE "done"
             /\ UNCHANGED <<generation, dbOld, viewGen, uiOld, page, connected, outage>>
PersistWire == /\ wire = "checked" /\ dbOld' = IF generation = 0 THEN TRUE ELSE dbOld
               /\ wire' = "inflight"
               /\ UNCHANGED <<generation, viewGen, uiOld, page, connected, outage>>
DeliverWire == /\ wire = "inflight" /\ wire' = "done"
               /\ uiOld' = IF connected /\ (~FenceClient \/ viewGen = 0) THEN TRUE ELSE uiOld
               /\ UNCHANGED <<generation, dbOld, viewGen, page, connected, outage>>
ReadPage == /\ page = 2 /\ connected /\ page' = generation
            /\ UNCHANGED <<generation, dbOld, viewGen, uiOld, wire, connected, outage>>
DeliverPage == /\ page \in {0,1} /\ connected
               /\ LET accept == ~FenceClient \/ page >= viewGen IN
                     /\ uiOld' = IF accept THEN page = 0 ELSE uiOld
                     /\ viewGen' = IF accept THEN page ELSE viewGen
               /\ page' = 3 /\ UNCHANGED <<generation, dbOld, wire, connected, outage>>
Adopt == /\ connected /\ generation = 1 /\ viewGen = 0 /\ viewGen' = 1 /\ uiOld' = FALSE
         /\ UNCHANGED <<generation, dbOld, wire, page, connected, outage>>
Disconnect == /\ connected /\ ~outage /\ connected' = FALSE /\ outage' = TRUE
              /\ UNCHANGED <<generation, dbOld, viewGen, uiOld, wire, page>>
Reconnect == /\ ~connected /\ connected' = TRUE
             /\ UNCHANGED <<generation, dbOld, viewGen, uiOld, wire, page, outage>>
Done == /\ viewGen = 1 /\ wire = "done" /\ page = 3 /\ connected /\ outage
        /\ UNCHANGED vars
Next == Replace \/ CheckWire \/ PersistWire \/ DeliverWire \/ ReadPage \/ DeliverPage
        \/ Adopt \/ Disconnect \/ Reconnect \/ Done
RetiredWriteIgnored == generation = 0 \/ ~dbOld
RetiredEventIgnored == viewGen = 0 \/ ~uiOld
NoViewRewind == [][viewGen' >= viewGen]_vars
============================================================================
