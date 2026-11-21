---------------------------- MODULE EditAdmission ----------------------------
EXTENDS Naturals, Sequences

\* Two editors and a transport retry of A initially selected the same revision.
\* Actors are attempts, not turn IDs: the retry carries exactly A's payload.
CONSTANT CheckSource
Attempts == {"A", "B", "retryA"}
Turn(i) == IF i = "retryA" THEN "A" ELSE i
VARIABLES phase, lane, normal, model, display, writes, runs, receipt, staleWrite
vars == <<phase, lane, normal, model, display, writes, runs, receipt, staleWrite>>
Old == <<"prefix", "original", "suffix">>
Init == /\ phase = [i \in Attempts |-> "start"] /\ lane = "idle"
        /\ normal = "start" /\ model = Old /\ display = Old
        /\ writes = <<>> /\ runs = <<>> /\ receipt = "none" /\ staleWrite = FALSE

\* The source was selected earlier. A busy attempt can only consult the durable receipt.
Reserve(i) == /\ phase[i] = "start"
              /\ IF lane = "idle" THEN /\ lane' = i /\ phase' = [phase EXCEPT ![i] = "reserved"]
                                    ELSE /\ UNCHANGED lane /\ phase' = [phase EXCEPT ![i] = "retryOnly"]
              /\ UNCHANGED <<normal, model, display, writes, runs, receipt, staleWrite>>
CheckReceipt(i) == /\ phase[i] \in {"retryOnly", "reserved"}
                   /\ (phase[i] = "retryOnly" \/ receipt = Turn(i))
                   /\ phase' = [phase EXCEPT ![i] = IF receipt = Turn(i) THEN "reply" ELSE "rejected"]
                   /\ lane' = IF lane = i THEN "idle" ELSE lane
                   /\ UNCHANGED <<normal, model, display, writes, runs, receipt, staleWrite>>
\* Whole transaction fails, or source no longer matches inside its write lock.
AbortEdit(i) == /\ phase[i] = "reserved" /\ lane = i
                /\ phase' = [phase EXCEPT ![i] = "rejected"] /\ lane' = "idle"
                /\ UNCHANGED <<normal, model, display, writes, runs, receipt, staleWrite>>
Commit(i) == /\ phase[i] = "reserved" /\ lane = i /\ receipt # Turn(i)
             /\ (~CheckSource \/ model = Old)
             /\ model' = <<"prefix", Turn(i)>> /\ display' = <<"prefix", Turn(i)>>
             /\ receipt' = Turn(i) /\ writes' = Append(writes, Turn(i))
             /\ staleWrite' = (staleWrite \/ model # Old)
             /\ phase' = [phase EXCEPT ![i] = "committed"] /\ UNCHANGED <<lane, normal, runs>>
\* The observer may disconnect. The shielded owner still hands work to the queue.
Enqueue(i) == /\ phase[i] = "committed" /\ phase' = [phase EXCEPT ![i] = "queued"]
              /\ UNCHANGED <<lane, normal, model, display, writes, runs, receipt, staleWrite>>
Run(i) == /\ phase[i] = "queued" /\ lane = i /\ runs' = Append(runs, Turn(i))
          /\ lane' = "idle" /\ phase' = [phase EXCEPT ![i] = "reply"]
          /\ UNCHANGED <<normal, model, display, writes, receipt, staleWrite>>

\* Normal input can arrive at any await, including between Commit and Enqueue.
Arrive == /\ normal = "start" /\ normal' = "waiting"
          /\ UNCHANGED <<phase, lane, model, display, writes, runs, receipt, staleWrite>>
NormalAdmit == /\ normal = "waiting" /\ lane = "idle" /\ normal' = "active" /\ lane' = "normal"
               /\ UNCHANGED <<phase, model, display, writes, runs, receipt, staleWrite>>
NormalSave == /\ normal = "active" /\ normal' = "done" /\ lane' = "idle"
              /\ model' = Append(model,"N") /\ display' = Append(display,"N")
              /\ UNCHANGED <<phase, writes, runs, receipt, staleWrite>>
Terminal == /\ normal = "done" /\ \A i \in Attempts : phase[i] \in {"reply", "rejected"}
Done == Terminal /\ UNCHANGED vars
Next == (\E i \in Attempts : Reserve(i) \/ CheckReceipt(i) \/ AbortEdit(i) \/ Commit(i) \/ Enqueue(i) \/ Run(i))
        \/ Arrive \/ NormalAdmit \/ NormalSave \/ Done

SourceStillCurrent == ~staleWrite
OneWinner == Len(writes) <= 1
OrderedExecution == /\ Len(runs) <= Len(writes)
                    /\ runs = SubSeq(writes, 1, Len(runs))
                    /\ (Terminal => runs = writes)
AtomicReplacement == /\ model = display /\ (Len(writes) = 0 => receipt = "none")
                     /\ (Len(writes) > 0 => receipt = writes[Len(writes)])
NoLostNormal == normal # "done" \/ model[Len(model)] = "N"
=============================================================================
