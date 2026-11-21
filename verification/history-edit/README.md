# Editing a persisted user message

Two bounded TLA+ models cover ordering in a single session. They check different properties, not a proof of their composition or of the entire gateway.

| Model | Interleavings | Implementation and executable checks |
| --- | --- | --- |
| `EditAdmission` | Two editors select the same prefix, one retries with the same turn ID and payload, and an ordinary input arrives. Admission, a successful or failed transaction, queue handoff and execution are separate actions. At most one edit of that revision may win; a retry must not run it twice, and ordinary input must not disappear. | `AgentLoop.replace_user_input`, `SessionInboxes` and `SessionState.replace_user_input`. Receipt matching, source validation and both history writes are in the SQLite transaction. [Admission tests](../../tests/agent/test_loop_history_edit.py) hold a real write open across ordinary input or observer cancellation. [Storage tests](../../tests/webui/test_history_replacement.py) terminate a child process on either side of commit and reopen the database. |
| `RetiredDelivery` | An outbound event and an HTTP page can be checked or captured before replacement but delivered afterwards, across one disconnect/reconnect. Once the client has adopted the replacement, neither the old content nor the old generation may reappear. | `WebUIOutboundDelivery`, generation-checked `append_history`, `NanobotClient.adoptHistorySnapshot` and `ThreadTranscript`. [Gateway tests](../../tests/webui/test_message_edit.py) exercise delivery to the channel; [client](../../webui/src/tests/nanobot-client.test.ts) and [transcript](../../webui/src/tests/thread-transcript.test.ts) tests exercise the consumer. |

In the admission model, `Run` is the execution claim for the already-persisted edit, not the completion of a model request. The normal input's effective position in the history is modeled; queue journal implementation, token streaming and the provider's behavior are not. The model assumes one session execution owner and SQLite transaction atomicity. In the delivery model, 0 and 1 label two opaque generations in their observed order, not values the application may numerically compare. A disconnected browser can still display an old view until it receives the new snapshot. The models check safety and deadlocks at these bounds; they do not establish unbounded progress, exactly-once external tool effects, or correctness under disk corruption.

## Reproduce

Copy this directory into a scratch directory. With [TLC 2.19 from TLA+ v1.7.4](https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4), run:

```text
java -XX:+UseParallelGC -cp /path/to/tla2tools.jar tlc2.TLC -workers 1 -config admission.cfg EditAdmission.tla
java -XX:+UseParallelGC -cp /path/to/tla2tools.jar tlc2.TLC -workers 1 -config delivery.cfg RetiredDelivery.tla
```

For sensitivity checks, set `CheckSource = FALSE` or `FenceClient = FALSE` in a scratch copy of the corresponding config. The first permits a normal input to be saved after selection and then overwritten by a stale edit. The second permits an old page or frame to overwrite an already-adopted replacement. These are negative controls on the models, not claims about executing those variants in production.
