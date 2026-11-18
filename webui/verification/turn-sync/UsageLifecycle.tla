------------------------- MODULE UsageLifecycle -------------------------
EXTENDS Naturals, FiniteSets, Sequences, TLC
\* Per-chat server/ledger composition, plus dynamic selected vs actually mounted
\* transcript and separate reconnect/own-read continuations. H/R captures are an
\* independent-producer OVERAPPROXIMATION: concrete sharing/abort is partitioned
\* into SharedRequests, not asserted equivalent. A counterexample needs mapping.
\* Full pages contain all bounded persisted IDs; no fragment-gap bridging proof.
\* Effect setup starts history (useNanobotStream:551) before transcript subscribe
\* (:682 onward), so selected alone does not imply hasTranscript.
CONSTANTS NChats, NTurns, MaxOutages, MaxSwitches, AllowFailures, Fragments
Chats == 1..NChats
Turns == 1..NTurns
Readers == {"H", "R"}
None == 0
EmptyRead == [phase |-> 0, generation |-> 0, turn |-> 0,
              completed |-> {}, observed |-> {}, pending |-> FALSE, active |-> 0, fragment |-> FALSE]
EmptyLedger == [open |-> {}, closed |-> {}, fenced |-> {}, latest |-> 0,
                clock |-> 0, generation |-> 0, anonymous |-> FALSE,
                recoverySeen |-> FALSE, learned |-> {}]
VARIABLES server, wire, ledger, reads, needHook, selected, mounted, switches,
          connected, outages, safe
vars == <<server, wire, ledger, reads, needHook, selected, mounted, switches,
          connected, outages, safe>>
Active(c) == ledger[c].open # {} \/ ledger[c].clock # 0 \/ ledger[c].anonymous
Done(c) == {t \in Turns : server[c][t] = 2}
Running(c) == {t \in Turns : server[c][t] = 1}
Seen(c) == {t \in Turns : server[c][t] # 0}
NewRead(c) == [EmptyRead EXCEPT !.phase = 1,
              !.generation = ledger[c].generation, !.turn = ledger[c].latest]
Init ==
 /\ server = [c \in Chats |-> [t \in Turns |-> 0]]
 /\ wire = [c \in Chats |-> <<>>]
 /\ ledger = [c \in Chats |-> EmptyLedger]
 /\ reads = [c \in Chats |-> [r \in Readers |-> EmptyRead]]
 /\ needHook = {}
 /\ selected = 0 /\ mounted = 0 /\ switches = 0 /\ connected = TRUE /\ outages = 0
 /\ safe = [collateral |-> TRUE, partial |-> TRUE, lifecycle |-> TRUE,
            activeAdoption |-> TRUE, cacheOrder |-> TRUE, handoff |-> TRUE, soleActor |-> TRUE]
Start(c,t) ==
 /\ UNCHANGED mounted
 /\ server[c][t] = 0 /\ (IF t = 1 THEN TRUE ELSE server[c][t-1] = 2)
 /\ server' = [server EXCEPT ![c][t] = 1]
 /\ wire' = IF connected THEN [wire EXCEPT ![c] = Append(@, [kind |-> 1, turn |-> t])] ELSE wire
 /\ UNCHANGED <<ledger, reads, needHook, selected, mounted, switches, connected, outages, safe>>
Finish(c,t) ==
 /\ UNCHANGED mounted
 /\ server[c][t] = 1
 /\ server' = [server EXCEPT ![c][t] = 2]
 /\ wire' = IF connected THEN [wire EXCEPT ![c] = Append(@, [kind |-> 2, turn |-> t])] ELSE wire
 /\ UNCHANGED <<ledger, reads, needHook, selected, mounted, switches, connected, outages, safe>>
Disconnect ==
 /\ UNCHANGED mounted
 /\ connected /\ outages < MaxOutages
 /\ connected' = FALSE /\ outages' = outages+1
 /\ wire' = [c \in Chats |-> <<>>]
 /\ reads' = [c \in Chats |-> [reads[c] EXCEPT !["R"] = EmptyRead]]
 /\ UNCHANGED <<server, ledger, needHook, selected, mounted, switches, safe>>
Reconnect ==
 /\ UNCHANGED mounted
 /\ ~connected /\ connected' = TRUE
 /\ wire' = [c \in Chats |-> IF Running(c) = {} THEN <<>> ELSE
                      <<[kind |-> 1, turn |-> CHOOSE t \in Running(c) : TRUE]>>]
 /\ reads' = [c \in Chats |-> [reads[c] EXCEPT !["R"] = IF Active(c) THEN NewRead(c) ELSE EmptyRead]]
 /\ needHook' = IF selected # 0 THEN needHook \cup {selected} ELSE needHook
 /\ UNCHANGED <<server, ledger, selected, switches, outages, safe>>
Switch(c) ==
 /\ c \in Chats \cup {0} /\ c # selected /\ switches < MaxSwitches
 /\ selected' = c /\ mounted' = 0 /\ switches' = switches+1
 /\ reads' = IF selected = 0 THEN reads ELSE [reads EXCEPT ![selected]["H"] = EmptyRead]
 /\ needHook' = IF c = 0 THEN {} ELSE {c}
 /\ UNCHANGED <<server, wire, ledger, connected, outages, safe>>
HookEffect ==
 /\ selected # 0 /\ selected \in needHook
 /\ reads' = [reads EXCEPT ![selected]["H"] = NewRead(selected)]
 /\ mounted' = selected
 /\ needHook' = needHook \ {selected}
 /\ UNCHANGED <<server, wire, ledger, selected, switches, connected, outages, safe>>
Receive(c) ==
 /\ UNCHANGED mounted
 /\ connected /\ Len(wire[c]) > 0
 /\ LET m == Head(wire[c])
        l == ledger[c]
        ignored == m.turn \in l.fenced \/ (m.kind = 1 /\ m.turn \in l.closed)
        nl == IF ignored THEN l ELSE IF m.kind = 1 THEN
               [l EXCEPT !.open = @ \cup {m.turn}, !.latest = m.turn, !.clock = m.turn,
                         !.generation = @+1, !.anonymous = FALSE]
             ELSE [l EXCEPT !.open = @ \ {m.turn}, !.closed = @ \cup {m.turn},
                         !.clock = IF l.latest = 0 \/ l.latest = m.turn THEN 0 ELSE @,
                         !.anonymous = IF l.latest = 0 \/ l.latest = m.turn THEN FALSE ELSE @]
    IN /\ ledger' = [ledger EXCEPT ![c] = nl]
       /\ reads' = IF ~ignored /\ m.kind = 2 THEN
            [reads EXCEPT ![c] = [r \in Readers |-> IF reads[c][r].phase # 0
                                  THEN [reads[c][r] EXCEPT !.phase = 1, !.completed = {},
                                        !.observed = {}, !.pending = FALSE, !.active = 0, !.fragment = FALSE]
                                  ELSE reads[c][r]]]
            ELSE reads
 /\ wire' = [wire EXCEPT ![c] = Tail(@)]
 /\ UNCHANGED <<server, needHook, selected, mounted, switches, connected, outages, safe>>
Capture(c,r,fragment,completions,pending) ==
 /\ UNCHANGED mounted
 /\ reads[c][r].phase = 1
 /\ fragment \in BOOLEAN /\ (fragment => Fragments)
 /\ IF fragment THEN completions \subseteq Done(c) ELSE completions = Done(c)
 /\ pending \in BOOLEAN /\ (pending => (Running(c) # {} \/ ledger[c].anonymous))
 /\ reads' = [reads EXCEPT ![c][r].phase = 2, ![c][r].completed = completions,
                  ![c][r].observed = Seen(c), ![c][r].pending = pending,
                  ![c][r].active = IF Running(c) = {} THEN 0 ELSE CHOOSE t \in Running(c) : TRUE,
                  ![c][r].fragment = fragment]
 /\ UNCHANGED <<server, wire, ledger, needHook, selected, mounted, switches, connected, outages, safe>>
Process(c,r,accepted,exposed) ==
 /\ UNCHANGED mounted
 /\ reads[c][r].phase = 2 /\ (r = "R" => connected) /\ (r = "H" => mounted = c)
 /\ accepted \in BOOLEAN /\ exposed \in BOOLEAN /\ (exposed => accepted)
 /\ LET q == reads[c][r]
        l == ledger[c]
        completed == q.completed
        canApply == l.open \subseteq (completed \cup l.fenced) /\
                    (l.generation = q.generation \/ l.latest \in (completed \cup l.fenced))
        explicit == q.turn # 0 /\ q.turn \in completed
        idle == ~q.pending /\ q.active = 0
        canCache == IF q.fragment THEN canApply ELSE
                     (explicit \/ idle) /\ (q.turn = 0 \/ explicit \/ q.turn \in q.observed) /\ canApply
        hasOwner == mounted = c
        cacheInstall == r = "R" /\ canCache /\ hasOwner
        fragmentReady == q.fragment /\ ((r = "H" /\ exposed) \/
                           (r = "R" /\ (~hasOwner \/ (cacheInstall /\ exposed))))
        \* Transcript acceptance controls adoption, not exact full-page closure.
        \* exposed is separate: a staged accepted fragment can expose no IDs.
        \* Non-seed full-page owner handoff; no pending fragment gap here.
        ownerWhole == ~q.fragment /\ (r = "H" \/ cacheInstall)
        backgroundWhole == ~q.fragment /\ r = "R" /\ canCache /\ idle /\ ~hasOwner
        whole == ownerWhole \/ backgroundWhole
        \* Preflight/cache publication above still use the BEFORE-settlement ledger.
        \* A fresh, nonaborted full R page now supplies lifecycle evidence even
        \* with a mounted owner or canCache=FALSE. It grants no content coverage.
        lifecycle == fragmentReady \/ (r = "R" /\ ~q.fragment)
        doSettle == whole \/ lifecycle
        adopt == backgroundWhole \/ (ownerWhole /\ accepted /\ ~q.pending /\ canApply)
        nextOpen == IF doSettle THEN l.open \ completed ELSE l.open
        nextClock == IF adopt \/ (doSettle /\ l.latest \in completed) THEN 0 ELSE l.clock
        nextAnon == IF adopt THEN FALSE ELSE l.anonymous
        nl == [l EXCEPT !.open = nextOpen,
                     !.closed = IF doSettle THEN @ \cup completed ELSE @,
                     !.fenced = IF whole THEN @ \cup completed ELSE @,
                     !.clock = nextClock, !.anonymous = nextAnon,
                     !.learned = @ \cup (IF ~q.fragment \/ fragmentReady THEN completed ELSE {})]
    IN /\ ledger' = [ledger EXCEPT ![c] = nl]
       /\ reads' = [reads EXCEPT ![c][r] = EmptyRead,
           ![c]["H"] = IF cacheInstall \/ r = "H" THEN EmptyRead ELSE reads[c]["H"]]
       /\ safe' = [safe EXCEPT
           !.collateral = @ /\ ((l.open \ completed) \subseteq nextOpen) /\
                         (l.latest # 0 /\ l.latest \notin completed /\ l.clock = l.latest => nextClock = l.clock),
           !.partial = @ /\ (adopt \/ ~l.anonymous \/ nextAnon),
           !.lifecycle = @ /\ (~(lifecycle /\ ~whole) \/
                                  (nl.fenced = l.fenced /\ nextAnon = l.anonymous)),
           !.activeAdoption = @ /\ (~(r = "R" /\ ~hasOwner /\ ~q.fragment /\ ~idle) \/ ~adopt),
           !.cacheOrder = @ /\ (r # "R" \/ ~adopt \/ canCache),
           !.handoff = @ /\ (~doSettle \/ completed \cap nextOpen = {}),
           !.soleActor = @ /\ ~(ownerWhole /\ backgroundWhole)]
 /\ UNCHANGED <<server, wire, needHook, selected, mounted, switches, connected, outages>>
Fail(c,r) ==
 /\ UNCHANGED mounted
 /\ AllowFailures /\ reads[c][r].phase # 0
 /\ reads' = [reads EXCEPT ![c][r] = EmptyRead]
 /\ UNCHANGED <<server, wire, ledger, needHook, selected, mounted, switches, connected, outages, safe>>
BeginRecovery(c) ==
 /\ UNCHANGED mounted
 /\ connected /\ Running(c) # {} /\ ~ledger[c].anonymous /\ ~ledger[c].recoverySeen
 /\ ledger' = [ledger EXCEPT ![c].anonymous = TRUE, ![c].recoverySeen = TRUE]
 /\ UNCHANGED <<server, wire, reads, needHook, selected, mounted, switches, connected, outages, safe>>
EndRecovery(c) ==
 /\ UNCHANGED mounted
 /\ connected /\ ledger[c].anonymous /\ Done(c) = Turns
 /\ ledger' = [ledger EXCEPT ![c].closed = @ \cup ledger[c].open \cup
                       (IF ledger[c].latest = 0 THEN {} ELSE {ledger[c].latest}),
                      ![c].open = {}, ![c].clock = 0, ![c].latest = 0, ![c].anonymous = FALSE]
 /\ UNCHANGED <<server, wire, reads, needHook, selected, mounted, switches, connected, outages, safe>>
CaptureAny(c,r) == \E f,p \in BOOLEAN, d \in SUBSET Turns : Capture(c,r,f,d,p)
ProcessAny(c,r) == \E a,e \in BOOLEAN : Process(c,r,a,e)
Next ==
 \/ \E c \in Chats, t \in Turns : Start(c,t) \/ Finish(c,t)
 \/ Disconnect \/ Reconnect \/ HookEffect
 \/ \E c \in Chats \cup {0} : Switch(c)
 \/ \E c \in Chats : Receive(c) \/ BeginRecovery(c) \/ EndRecovery(c)
 \/ \E c \in Chats, r \in Readers : CaptureAny(c,r) \/ ProcessAny(c,r) \/ Fail(c,r)
Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(Reconnect) /\ WF_vars(HookEffect) /\
            (\A c \in Chats : WF_vars(Receive(c))) /\
            (\A c \in Chats, r \in Readers : WF_vars(CaptureAny(c,r)) /\ WF_vars(ProcessAny(c,r)))
TypeOK ==
 /\ server \in [Chats -> [Turns -> 0..2]] /\ selected \in Chats \cup {0}
 /\ mounted \in Chats \cup {0} /\ (mounted # 0 => mounted = selected)
 /\ switches \in 0..MaxSwitches /\ outages \in 0..MaxOutages /\ connected \in BOOLEAN
 /\ needHook \subseteq Chats
 /\ \A c \in Chats : /\ ledger[c].open \subseteq Turns /\ ledger[c].closed \subseteq Turns
                     /\ ledger[c].fenced \subseteq Turns /\ ledger[c].latest \in Turns \cup {0}
                     /\ ledger[c].clock \in Turns \cup {0}
                     /\ ledger[c].generation \in 0..(NTurns+MaxOutages)
\* Raw processed full-page IDs were already included in learned regardless of
\* cache eligibility. Keep that definition, not just successful handoff IDs.
RawExplicitCompletionsSettle == \A c \in Chats : ledger[c].learned \cap ledger[c].open = {}
ExplicitCompletionsSettle == RawExplicitCompletionsSettle
NoOlderCompletionClearsNewer == safe.collateral
PartialCompletionPreservesRecovery == safe.partial
LifecycleOnlyPreservesContentAndRecovery == safe.lifecycle
ActiveUnmountedSnapshotIsNotAdopted == safe.activeAdoption
CachePrecedesIdleNotification == safe.cacheOrder
ExplicitCompletionHandoffSettles == safe.handoff
SoleCanonicalActor == safe.soleActor
Quiescent == connected /\ (\A c \in Chats : Done(c) = Turns /\ ~ledger[c].anonymous)
EventuallyIdle == [] (Quiescent => <>[] (\A c \in Chats : ~Active(c)))
=============================================================================
