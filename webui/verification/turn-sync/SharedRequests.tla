------------------------- MODULE SharedRequests -------------------------
EXTENDS Naturals, FiniteSets
CONSTANTS NChats, MaxOutages, MaxSwitches, MaxInvalidations
Chats == 1..NChats
Readers == {"H", "R"}
\* At most H and R actively await one key; each attaches to at most one network
\* object. Thus two live slots are sufficient, not an arbitrary request cutoff.
\* Released/aborted network identities with no consumers are observationally
\* merged into late[key]; they may deliver but cannot regain an active wrapper.
\* Same authenticated client/token, two distinct websocket:<chat> keys.
Slots == {1,2}
EmptyNet == [phase |-> 0, shareable |-> FALSE, baseline |-> 0, body |-> 0]
EmptyConsumer == [phase |-> 0, slot |-> 0, owner |-> 0, epoch |-> 0, body |-> 0]
VARIABLES net, current, consumers, selected, owner, connected, outages,
          switches, hookNeed, jobs, version, cache, invalidations, late,
          published, delivered, safe
vars == <<net, current, consumers, selected, owner, connected, outages,
          switches, hookNeed, jobs, version, cache, invalidations, late,
          published, delivered, safe>>
Attached(cs,i) == {r \in Readers : cs[r].phase = 1 /\ cs[r].slot = i}
Clean(ns,cs) == [i \in Slots |-> IF Attached(cs,i) = {} THEN EmptyNet ELSE ns[i]]
Pointer(p,ns) == IF p = 0 THEN 0 ELSE IF ns[p].phase = 0 THEN 0 ELSE p
Abandoned(ns,cs) == \E i \in Slots : ns[i].phase # 0 /\ Attached(cs,i) = {}
Init ==
 /\ net = [c \in Chats |-> [i \in Slots |-> EmptyNet]]
 /\ current = [c \in Chats |-> 0]
 /\ consumers = [c \in Chats |-> [r \in Readers |-> EmptyConsumer]]
 /\ selected = 1 /\ owner = 0 /\ connected = TRUE /\ outages = 0 /\ switches = 0
 /\ hookNeed = TRUE /\ jobs = Chats
 /\ version = [c \in Chats |-> 0] /\ cache = [c \in Chats |-> 0]
 /\ invalidations = [c \in Chats |-> 0] /\ late = {}
 /\ published = [c \in Chats |-> 0] /\ delivered = [c \in Chats |-> 0]
 /\ safe = [keyIsolation |-> TRUE, consumerEligibility |-> TRUE,
            lateNoEffect |-> TRUE, sharedIdentity |-> TRUE]
Start(c,r) ==
 /\ IF r = "H" THEN c = selected /\ hookNeed ELSE c \in jobs \/ consumers[c][r].phase = 3
 /\ LET cs == [consumers[c] EXCEPT ![r] = EmptyConsumer]
        ns == Clean(net[c],cs)
        ptr == Pointer(current[c],ns)
        join == IF ptr = 0 THEN FALSE ELSE ns[ptr].shareable /\ ns[ptr].baseline = cache[c]
        free == {i \in Slots : ns[i].phase = 0}
        id == IF join THEN ptr ELSE CHOOSE i \in free : \A j \in free : i <= j
        nc == [cs EXCEPT ![r] = [phase |-> 1, slot |-> id, owner |-> owner,
                                 epoch |-> outages, body |-> 0]]
        nn == IF join THEN ns ELSE [ns EXCEPT ![id] =
                  [phase |-> 1, shareable |-> connected, baseline |-> cache[c], body |-> 0]]
    IN /\ free # {} \/ join
       /\ consumers' = [consumers EXCEPT ![c] = nc]
       /\ net' = [net EXCEPT ![c] = nn]
       /\ current' = [current EXCEPT ![c] = id]
       /\ late' = IF Abandoned(net[c],cs) THEN late \cup {c} ELSE late
       /\ safe' = [safe EXCEPT !.sharedIdentity = @ /\ (~join \/ id = ptr)]
 /\ hookNeed' = IF r = "H" THEN FALSE ELSE hookNeed
 /\ jobs' = IF r = "R" THEN jobs \ {c} ELSE jobs
 /\ UNCHANGED <<selected, owner, connected, outages, switches, version, cache,
                invalidations, published, delivered>>
Switch(c) ==
 /\ c \in Chats \cup {0} /\ c # selected /\ switches < MaxSwitches
 /\ selected' = c /\ owner' = owner+1 /\ switches' = switches+1
 /\ hookNeed' = (c # 0)
 /\ LET cs == [k \in Chats |-> [consumers[k] EXCEPT !["H"] = EmptyConsumer]]
        ns == [k \in Chats |-> Clean(net[k],cs[k])]
    IN /\ consumers' = cs /\ net' = ns
       /\ current' = [k \in Chats |-> Pointer(current[k],ns[k])]
       /\ late' = late \cup {k \in Chats : Abandoned(net[k],cs[k]) \/ consumers[k]["H"].phase = 2}
 /\ UNCHANGED <<connected, outages, jobs, version, cache, invalidations, published, delivered, safe>>
Disconnect ==
 /\ connected /\ outages < MaxOutages
 /\ connected' = FALSE /\ outages' = outages+1 /\ jobs' = {}
 /\ LET cs == [c \in Chats |-> [consumers[c] EXCEPT !["R"] = EmptyConsumer]]
        ns == [c \in Chats |-> Clean([i \in Slots |-> [net[c][i] EXCEPT !.shareable = FALSE]],cs[c])]
    IN /\ consumers' = cs /\ net' = ns
       /\ current' = [c \in Chats |-> Pointer(current[c],ns[c])]
       /\ late' = late \cup {c \in Chats : Abandoned(net[c],cs[c]) \/ consumers[c]["R"].phase = 2}
 /\ UNCHANGED <<selected, owner, switches, hookNeed, version, cache, invalidations, published, delivered, safe>>
Reconnect ==
 /\ ~connected /\ connected' = TRUE /\ jobs' = Chats
 /\ hookNeed' = (selected # 0)
 /\ UNCHANGED <<net, current, consumers, selected, owner, outages, switches,
                version, cache, invalidations, late, published, delivered, safe>>
Invalidate(c) ==
 /\ invalidations[c] < MaxInvalidations
 /\ invalidations' = [invalidations EXCEPT ![c] = @+1]
 /\ version' = [version EXCEPT ![c] = @+1]
 /\ consumers' = [consumers EXCEPT ![c] = [r \in Readers |->
       IF consumers[c][r].phase = 1 THEN [consumers[c][r] EXCEPT !.phase = 3, !.slot = 0]
       ELSE consumers[c][r]]]
 /\ net' = [net EXCEPT ![c] = [i \in Slots |-> EmptyNet]]
 /\ current' = [current EXCEPT ![c] = 0]
 /\ late' = IF \E i \in Slots : net[c][i].phase # 0 THEN late \cup {c} ELSE late
 /\ UNCHANGED <<selected, owner, connected, outages, switches, hookNeed, jobs,
                cache, published, delivered, safe>>
RetryHook(c) ==
 /\ c = selected /\ consumers[c]["H"].phase = 3 /\ ~hookNeed
 /\ hookNeed' = TRUE
 /\ UNCHANGED <<net, current, consumers, selected, owner, connected, outages,
                switches, jobs, version, cache, invalidations, late, published, delivered, safe>>
Capture(c,i) ==
 /\ net[c][i].phase = 1
 /\ net' = [net EXCEPT ![c][i].phase = 2, ![c][i].body = version[c]]
 /\ UNCHANGED <<current, consumers, selected, owner, connected, outages, switches,
                hookNeed, jobs, version, cache, invalidations, late, published, delivered, safe>>
Resolve(c,i) ==
 /\ net[c][i].phase = 2
 /\ consumers' = [consumers EXCEPT ![c] = [r \in Readers |->
       IF consumers[c][r].phase = 1 /\ consumers[c][r].slot = i THEN
          [consumers[c][r] EXCEPT !.phase = 2, !.slot = 0, !.body = net[c][i].body]
       ELSE consumers[c][r]]]
 /\ net' = [net EXCEPT ![c][i] = EmptyNet]
 /\ current' = [current EXCEPT ![c] = IF @ = i THEN 0 ELSE @]
 /\ UNCHANGED <<selected, owner, connected, outages, switches, hookNeed, jobs,
                version, cache, invalidations, late, published, delivered, safe>>
Consume(c,r,publish) ==
 /\ consumers[c][r].phase = 2 /\ publish \in BOOLEAN
 /\ LET q == consumers[c][r]
        eligible == IF r = "H" THEN c = selected /\ q.owner = owner ELSE connected /\ q.epoch = outages
        didPublish == eligible /\ (r = "H" \/ publish)
        handoff == didPublish /\ c = selected
        cs == [consumers[c] EXCEPT ![r] = EmptyConsumer,
                    !["H"] = IF handoff \/ r = "H" THEN EmptyConsumer ELSE consumers[c]["H"]]
        ns == Clean(net[c],cs)
    IN /\ consumers' = [consumers EXCEPT ![c] = cs]
       /\ net' = [net EXCEPT ![c] = ns]
       /\ current' = [current EXCEPT ![c] = Pointer(@,ns)]
       /\ cache' = IF didPublish THEN [cache EXCEPT ![c] = @+1] ELSE cache
       /\ published' = IF didPublish THEN [published EXCEPT ![c] = q.body] ELSE published
       /\ delivered' = IF handoff THEN [delivered EXCEPT ![c] = q.body] ELSE delivered
       /\ late' = IF Abandoned(net[c],cs) \/ (handoff /\ consumers[c]["H"].phase = 2 /\ r # "H")
                  THEN late \cup {c} ELSE late
       /\ safe' = [safe EXCEPT
          !.keyIsolation = @ /\ (\A k \in Chats \ {c} : published'[k] = published[k] /\ delivered'[k] = delivered[k]),
          !.consumerEligibility = @ /\ (didPublish => eligible) /\ (handoff => c = selected)]
 /\ UNCHANGED <<selected, owner, connected, outages, switches, hookNeed, jobs,
                version, invalidations>>
LateDelivery(c) ==
 /\ c \in late /\ late' = late \ {c}
 /\ UNCHANGED <<net, current, consumers, selected, owner, connected, outages, switches,
                hookNeed, jobs, version, cache, invalidations, published, delivered, safe>>
StartAny == \E c \in Chats, r \in Readers : Start(c,r)
CaptureAny == \E c \in Chats, i \in Slots : Capture(c,i)
ResolveAny == \E c \in Chats, i \in Slots : Resolve(c,i)
ConsumeAny == \E c \in Chats, r \in Readers, p \in BOOLEAN : Consume(c,r,p)
RetryAny == \E c \in Chats : RetryHook(c)
Next == StartAny \/ CaptureAny \/ ResolveAny \/ ConsumeAny \/ RetryAny \/ Disconnect \/ Reconnect \/
        (\E c \in Chats \cup {0} : Switch(c)) \/ (\E c \in Chats : Invalidate(c) \/ LateDelivery(c))
Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(StartAny) /\ WF_vars(CaptureAny) /\ WF_vars(ResolveAny) /\
            WF_vars(ConsumeAny) /\ WF_vars(RetryAny) /\ WF_vars(Reconnect)
TypeOK ==
 /\ selected \in Chats \cup {0} /\ switches \in 0..MaxSwitches /\ outages \in 0..MaxOutages
 /\ connected \in BOOLEAN /\ jobs \subseteq Chats /\ late \subseteq Chats
 /\ \A c \in Chats : /\ current[c] \in Slots \cup {0}
                     /\ invalidations[c] \in 0..MaxInvalidations
                     /\ \A r \in Readers : consumers[c][r].phase \in 0..3
                     /\ \A i \in Slots : net[c][i].phase \in 0..2
NoWrongKeyDelivery == safe.keyIsolation
NoIneligibleConsumerDelivery == safe.consumerEligibility
NoOrphanedNetwork == \A c \in Chats, i \in Slots :
                       (net[c][i].phase # 0) => Attached(consumers[c],i) # {}
PointerHasRequest == \A c \in Chats : IF current[c] = 0 THEN TRUE ELSE net[c][current[c]].phase # 0
SharingUsesCurrentIdentity == safe.sharedIdentity
Quiescent == connected /\ ~hookNeed /\ jobs = {} /\
              (\A c \in Chats, r \in Readers : consumers[c][r].phase = 0)
EventuallyRequestsDrain == <>[] Quiescent
=============================================================================
