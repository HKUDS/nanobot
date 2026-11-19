------------------------- MODULE CacheHandoff -------------------------
EXTENDS Naturals, FiniteSets
CONSTANT ActiveTail
Chats == {1,2}
Turns == {1,2}
VARIABLES ledger, selected, owner, switches, phase, response,
          admitted, cached, ownReadSuperseded, ownReadOwner,
          learned, lateRejected, otherOriginal, soleActor
vars == <<ledger, selected, owner, switches, phase, response,
          admitted, cached, ownReadSuperseded, ownReadOwner,
          learned, lateRejected, otherOriginal, soleActor>>
Complete(l,ids,coverage) == [l EXCEPT !.open = @ \ ids, !.closed = @ \cup ids,
                  !.clock = IF l.latest \in ids THEN 0 ELSE @,
                  !.fenced = IF coverage = "content" THEN @ \cup ids ELSE @]
Init ==
 \* Reachable checkpoint: A is observed, initial active history already installed;
 \* disconnect lost A's terminal; reconnect R and H share one new request.
 \* Server has persisted turn 1 and is running turn 2, whose WS status is delayed.
 /\ ledger = [c \in Chats |-> [open |-> {1}, closed |-> {}, fenced |-> {},
                              latest |-> 1, clock |-> 1, anonymous |-> FALSE, generation |-> 1]]
 /\ selected = 1 /\ owner = 0 /\ switches = 0 /\ phase = 0
 /\ response = [completed |-> {}, active |-> 0, pending |-> FALSE]
 /\ admitted = FALSE /\ cached = FALSE /\ ownReadSuperseded = FALSE /\ ownReadOwner = 0
 /\ soleActor = TRUE
 /\ learned = {} /\ lateRejected = FALSE /\ otherOriginal = ledger[2]
Capture ==
 /\ phase = 0 /\ phase' = 1
 /\ response' = [completed |-> {1}, active |-> IF ActiveTail THEN 2 ELSE 0, pending |-> ActiveTail]
 /\ UNCHANGED <<ledger, selected, owner, switches, admitted, cached, ownReadSuperseded,
                ownReadOwner, learned, lateRejected, otherOriginal, soleActor>>
Switch(c) ==
 /\ c \in Chats \cup {0} /\ c # selected /\ switches < 2
 /\ selected' = c /\ owner' = owner+1 /\ switches' = switches+1
 /\ UNCHANGED <<ledger, phase, response, admitted, cached, ownReadSuperseded,
                ownReadOwner, learned, lateRejected, otherOriginal, soleActor>>
Process(accept) ==
 /\ phase = 1 /\ accept \in BOOLEAN
 /\ LET ids == response.completed
        hasOwner == selected = 1
        canApply == ledger[1].open \subseteq ids
        canCache == 1 \in ids /\ canApply
        idle == ~response.pending /\ response.active = 0
        publish == canCache
        ownerHandoff == publish /\ hasOwner
        \* R publishes an eligible cache BEFORE its unconditional lifecycle call.
        \* Owner content reconciliation remains the sole mounted canonical actor.
        ownerContent == ownerHandoff
        backgroundContent == publish /\ idle /\ ~hasOwner
        content == ownerContent \/ backgroundContent
        \* Admission permits adoption only, not explicit completion settlement.
        adopt == content /\ accept /\ ~response.pending /\ canApply
        next == Complete(ledger[1],ids,IF content THEN "content" ELSE "lifecycle")
    IN /\ ledger' = [ledger EXCEPT ![1] = IF adopt THEN [next EXCEPT !.anonymous = FALSE, !.clock = 0] ELSE next]
       /\ cached' = publish
       /\ ownReadSuperseded' = ownerHandoff
       /\ admitted' = (ownerHandoff /\ accept)
       /\ learned' = ids
       /\ soleActor' = (soleActor /\ ~(ownerContent /\ backgroundContent))
 /\ phase' = 2
 /\ UNCHANGED <<selected, owner, switches, response, ownReadOwner, lateRejected, otherOriginal>>
ReceiveRunningTwo ==
 /\ phase = 2 /\ phase' = 3
 /\ ledger' = [ledger EXCEPT ![1].open = @ \cup {2}, ![1].latest = 2,
                  ![1].clock = 2, ![1].generation = @+1]
 /\ UNCHANGED <<selected, owner, switches, response, admitted, cached, ownReadSuperseded,
                ownReadOwner, learned, lateRejected, otherOriginal, soleActor>>
ReceiveEndTwo ==
 /\ phase = 3 /\ phase' = 4
 /\ ledger' = [ledger EXCEPT ![1] = Complete(@,{2},"lifecycle")]
 /\ UNCHANGED <<selected, owner, switches, response, admitted, cached, ownReadSuperseded,
                ownReadOwner, learned, lateRejected, otherOriginal, soleActor>>
LateOwnResponse ==
 /\ phase = 4 /\ phase' = 5
 /\ lateRejected' = (ownReadSuperseded \/ owner # ownReadOwner)
 /\ UNCHANGED <<ledger, selected, owner, switches, response, admitted, cached,
                ownReadSuperseded, ownReadOwner, learned, otherOriginal, soleActor>>
Next == Capture \/ (\E c \in Chats \cup {0} : Switch(c)) \/
        (\E a \in BOOLEAN : Process(a)) \/ ReceiveRunningTwo \/ ReceiveEndTwo \/ LateOwnResponse
Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(Capture) /\ WF_vars(\E a \in BOOLEAN : Process(a)) /\
             WF_vars(ReceiveRunningTwo) /\ WF_vars(ReceiveEndTwo) /\ WF_vars(LateOwnResponse)
SoleCanonicalActor == soleActor
RawExplicitCompletionsSettle == phase < 2 \/ learned \cap ledger[1].open = {}
ExplicitCompletionsSettle == RawExplicitCompletionsSettle
OtherChatUnchanged == ledger[2] = otherOriginal
NoAnonymousClearedByNamedCompletion == ~ledger[1].anonymous
StaleOwnReadCannotOverwrite == phase < 5 \/ lateRejected \/ (selected = 1 /\ ~ownReadSuperseded /\ owner = ownReadOwner)
EventuallyIdle == <>[] (ledger[1].open = {} /\ ledger[1].clock = 0 /\ ~ledger[1].anonymous)
=============================================================================
