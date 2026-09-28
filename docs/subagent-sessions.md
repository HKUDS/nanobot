# Subagent sessions

Each delegated task has a durable `subagent:<task_id>` session in the active
instance's session store. Inline and background tasks use the same storage path.
The record is created before scheduling, so a task cancelled before admission
still has a transcript and terminal status.

`SubagentManager` owns scheduling, capacity, cancellation, and result delivery.
`ChildSessionService` owns task records and child process cleanup. Both ordinary
agent turns (including Dream) and child tasks execute through `SessionExecutor`,
which binds tool context and workspace scope and supplies shared prompt building
and compaction. Standalone SDK subagents use this executor without constructing
an `AgentLoop`.

## Inspecting a run

Use `SessionManager` with the same workspace and active config path as the agent:

```python
from nanobot.session.manager import SessionManager

sessions = SessionManager(workspace)
for item in sessions.list_sessions():
    if item["key"].startswith("subagent:"):
        session = sessions.get_or_create(item["key"])
        print(session.metadata["subagent"])
        print(session.messages)
```

The `subagent` metadata records the task ID, parent session key when provided,
model, workspace, access mode, lifecycle timestamps, and status (`queued`,
`running`, `completed`, `failed`, or `cancelled`). Execution adds the latest phase
and iteration; completed runs also record stop reason, error, and usage.
Background result messages include `subagent_session_key` in their metadata.

Tool checkpoints and completed tool rounds are saved during execution. The final
transcript retains tool calls, results, and the response; compaction checkpoints
preserve the original transcript while controlling model replay. Cancellation
materializes pending tool calls as interrupted results. After an abrupt process
exit, a nonterminal status and runtime checkpoint represent the last saved state;
loading the record does not automatically rerun tools or resume the task.

## Context and retention

Child tasks receive project instructions and agent skills, but do not inherit the
parent transcript or long-term memory. `agent/subagent_system.md` adds the delegated
role and result-delivery instructions to the system prompt, including after
compaction. The assigned task is a separate user message in both the model input
and saved transcript. Saving their session does not append their
summaries or raw fallbacks to the agent's memory archive. Like Dream's per-run
sessions, they are excluded from idle memory archival. Dream's session rotation
does not delete subagent records.

These are internal task records, not channel destinations. The existing session
store provides inspection; no dedicated subagent viewer is required for storage.
