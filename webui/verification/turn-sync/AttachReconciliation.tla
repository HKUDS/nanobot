----------------------- MODULE AttachReconciliation -----------------------
EXTENDS Naturals, FiniteSets, Sequences
CONSTANTS Reconcile, LateRecipients, HistoryResult, MaxLosses

Turns == {1, 2}
Local == 3
Idle == 0
\* Phase: 0 not admitted, 1 running, 2 awaiting terminal persistence,
\* 3 retired/durable, 4 retired/incomplete, 5 retired via named idle.
VARIABLES phase, captured, socket, connection, wire, oldCallback, client,
          history, probed, safe
vars == <<phase, captured, socket, connection, wire, oldCallback, client,
          history, probed, safe>>
Live == {t \in Turns : phase[t] \in {1, 2}}
Retired(t) == phase[t] >= 3
Subscribed == connection \in {"metadata", "hydrate", "ready"}
Frame(kind, id, ids) == [kind |-> kind, id |-> id, ids |-> ids]
Running(t) == Frame("running", t, {})
NoFrame == Frame("none", Idle, {})

Init ==
 /\ phase = [t \in Turns |-> IF t = 1 THEN 1 ELSE 0]
 /\ captured = [t \in Turns |-> Idle]
 /\ socket = 1 /\ connection = "ready"
 \* Turn 1 was confirmed over this socket. A duplicate running callback may lag.
 /\ wire = <<Running(1)>> /\ oldCallback = [socket |-> Idle, frame |-> NoFrame]
 /\ client = [open |-> {1}, marked |-> {}, closed |-> {}, clock |-> 1,
               anonymous |-> FALSE, fenced |-> {}, successes |-> {}]
 /\ history = "pending" /\ probed = FALSE /\ safe = TRUE

LoseTransport ==
 /\ connection # "down" /\ socket <= MaxLosses
 /\ socket' = socket + 1 /\ connection' = "down" /\ wire' = <<>>
 /\ oldCallback' = IF wire = <<>> THEN oldCallback ELSE [socket |-> socket, frame |-> Head(wire)]
 \* 3 has a queued send but has not had a server observation.
 /\ client' = [client EXCEPT !.marked = client.open \cap Turns]
 /\ UNCHANGED <<phase, captured, history, probed, safe>>
Reconnect ==
 /\ connection = "down" /\ connection' = "open"
 /\ UNCHANGED <<phase, captured, socket, wire, oldCallback, client, history, probed, safe>>
Subscribe ==
 /\ connection = "open" /\ connection' = "metadata"
 /\ UNCHANGED <<phase, captured, socket, wire, oldCallback, client, history, probed, safe>>
EnqueueAttached ==
 /\ connection = "metadata" /\ connection' = "hydrate"
 \* Metadata await is before this atomic sample + enqueue on the same FIFO.
 /\ wire' = Append(wire, Frame("attached", Idle, Live))
 /\ UNCHANGED <<phase, captured, socket, oldCallback, client, history, probed, safe>>
Hydrate ==
 /\ connection = "hydrate" /\ connection' = "ready"
 \* Ordinary running hydration is a separate, ordered observation, not presence.
 /\ wire' = IF Live = {} THEN wire ELSE Append(wire, Running(IF 2 \in Live THEN 2 ELSE 1))
 /\ UNCHANGED <<phase, captured, socket, oldCallback, client, history, probed, safe>>

StartNewer ==
 /\ phase[1] >= 2 /\ phase[2] = 0
 /\ phase' = [phase EXCEPT ![2] = 1]
 /\ wire' = IF Subscribed THEN Append(wire, Running(2)) ELSE wire
 /\ UNCHANGED <<captured, socket, connection, oldCallback, client, history, probed, safe>>
BeginPersistence(t) ==
 /\ phase[t] = 1 /\ phase' = [phase EXCEPT ![t] = 2]
 /\ captured' = [captured EXCEPT ![t] = IF ~LateRecipients /\ Subscribed THEN socket ELSE Idle]
 /\ UNCHANGED <<socket, connection, wire, oldCallback, client, history, probed, safe>>
DeliverTerminal(t, outcome) ==
 /\ IF outcome = 5 THEN phase[t] = 1 ELSE phase[t] = 2
 /\ phase' = [phase EXCEPT ![t] = outcome]
 /\ captured' = [captured EXCEPT ![t] = Idle]
 \* (4) can retain an incomplete transcript record but still retires the owner.
 \* Named idle (5) has no terminal persistence await in this abstraction.
 /\ LET target == Subscribed /\ (outcome = 5 \/ LateRecipients \/ captured[t] = socket)
        kind == IF outcome = 5 THEN "idle" ELSE "terminal"
    IN wire' = IF target THEN Append(wire, Frame(kind, t, {})) ELSE wire
 /\ UNCHANGED <<socket, connection, oldCallback, client, history, probed, safe>>

SubmitLocal ==
 /\ Local \notin client.open
 /\ client' = [client EXCEPT !.open = @ \cup {Local}]
 /\ UNCHANGED <<phase, captured, socket, connection, wire, oldCallback, history, probed, safe>>
BeginAnonymous ==
 /\ socket > 1 /\ ~client.anonymous
 /\ client' = [client EXCEPT !.anonymous = TRUE]
 /\ UNCHANGED <<phase, captured, socket, connection, wire, oldCallback, history, probed, safe>>
HistoryWithoutID ==
 /\ socket > 1 /\ history = "pending" /\ history' = HistoryResult
 /\ UNCHANGED <<phase, captured, socket, connection, wire, oldCallback, client, probed, safe>>

Close(c, ids) == [c EXCEPT !.open = @ \ ids, !.marked = @ \ ids, !.closed = @ \cup ids,
                           !.clock = IF c.clock \in ids THEN Idle ELSE @]
Observe(c, msg) ==
 CASE msg.kind = "attached" -> IF Reconcile THEN Close(c, c.marked \ msg.ids) ELSE c
   [] msg.kind \in {"running", "delta"} ->
        IF msg.id \in c.closed THEN c ELSE [c EXCEPT !.open = @ \cup {msg.id}, !.clock = msg.id]
   [] msg.kind = "terminal" -> Close([c EXCEPT !.successes = @ \cup {msg.id}], {msg.id})
   [] msg.kind = "idle" -> Close(c, {msg.id})
   [] OTHER -> c

AttachEffects(before, after, live) ==
 LET absent == {t \in before.open \cap Turns : t \in before.marked /\ t \notin live}
 IN /\ before.open \ after.open = (IF Reconcile THEN absent ELSE {})
    /\ after.open \subseteq before.open
    /\ before.closed \subseteq after.closed
    /\ after.closed \ before.closed = (IF Reconcile THEN absent ELSE {})
    /\ (before.clock \in after.open => after.clock = before.clock)
    /\ after.anonymous = before.anonymous
    /\ after.fenced = before.fenced
    /\ after.successes = before.successes
Receive ==
 /\ Subscribed /\ wire # <<>>
 /\ LET msg == Head(wire)
    IN /\ client' = Observe(client, msg)
       /\ safe' = safe /\ (msg.kind = "attached" => AttachEffects(client, client', msg.ids))
 /\ wire' = Tail(wire)
 /\ UNCHANGED <<phase, captured, socket, connection, oldCallback, history, probed>>
ReceiveOld ==
 /\ connection # "down" /\ oldCallback.frame # NoFrame
 /\ client' = IF oldCallback.socket = socket THEN Observe(client, oldCallback.frame) ELSE client
 /\ safe' = safe /\ client' = client
 /\ oldCallback' = [socket |-> Idle, frame |-> NoFrame]
 /\ UNCHANGED <<phase, captured, socket, connection, wire, history, probed>>
ReplayBuffered(kind) ==
 /\ socket > 1 /\ Subscribed /\ ~probed /\ 1 \in client.closed
 \* One pre-closure buffered lifecycle-capable event; not a transcript probe.
 /\ client' = Observe(client, Frame(kind, 1, {}))
 /\ safe' = safe /\ client' = client
 /\ probed' = TRUE
 /\ UNCHANGED <<phase, captured, socket, connection, wire, oldCallback, history>>

Next ==
 \/ LoseTransport \/ Reconnect \/ Subscribe \/ EnqueueAttached \/ Hydrate
 \/ StartNewer \/ (\E t \in Turns: BeginPersistence(t) \/ (\E outcome \in 3..5: DeliverTerminal(t, outcome)))
 \/ SubmitLocal \/ BeginAnonymous \/ HistoryWithoutID
 \/ Receive \/ ReceiveOld \/ (\E kind \in {"running", "delta"}: ReplayBuffered(kind))

\* No fairness for starting/finishing work, local/anonymous activity, HTTP,
\* replay, or causing another loss. Healthy transport eventually drains.
FairSpec == Init /\ [][Next]_vars /\ WF_vars(Reconnect) /\ WF_vars(Subscribe)
                 /\ WF_vars(EnqueueAttached) /\ WF_vars(Hydrate) /\ WF_vars(Receive)
TypeOK ==
 /\ phase \in [Turns -> 0..5] /\ captured \in [Turns -> 0..(MaxLosses+1)]
 /\ socket \in 1..(MaxLosses+1)
 /\ connection \in {"down", "open", "metadata", "hydrate", "ready"}
 /\ client.open \subseteq Turns \cup {Local} /\ client.closed \subseteq Turns
 /\ client.marked \subseteq client.open \cap Turns /\ client.clock \in Turns \cup {Idle}
 /\ client.anonymous \in BOOLEAN /\ client.fenced = {} /\ client.successes \subseteq Turns
 /\ history \in {"pending", HistoryResult}
LifecycleSafety ==
 /\ safe /\ client.closed \cap client.open = {}
 /\ (client.clock = Idle \/ client.clock \in client.open)
 /\ client.closed \cap Live = {}
 /\ \A t \in client.successes: phase[t] \in {3, 4}
Healthy == socket > 1 /\ connection = "ready"
\* On stable reconnect and actual retirement, both absence and later terminal
\* are sufficient. Do not require that an executing turn or local send finishes.
EventuallyRetiredOwnersSettle ==
 \A t \in Turns: (<>[] Healthy /\ <>[] Retired(t)) => <>[] (t \notin client.open)
=============================================================================
