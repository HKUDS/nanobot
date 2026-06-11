# Cron / Session / Memory Design Decisions

This note records the agreed design direction for fixing the mismatch between
scheduled automations and chat session memory.

## Problem

User-created cron jobs currently run their agent turn under an internal key such
as `cron:{job.id}` and only deliver the final response back to the user channel.
That splits the turn's working memory from the session where the user sees and
continues the conversation.

The visible failure mode is awkward: a cron job reports something into a chat,
the user discusses it in that chat, and the next cron run behaves as if that
discussion never happened.

The fix is not to make cron a separate delivery system. A user automation should
be a scheduled input into a session.

## Core Model

For new user-created cron jobs, `payload.session_key` is the canonical anchor.

- The cron job belongs to that session.
- The cron job reads that session's memory/history.
- The cron job produces a normal session turn.
- There is no separate delivery target concept for new jobs.

Legacy fields remain in the store only for compatibility:

- `payload.channel`
- `payload.to`
- `payload.channel_meta`
- `payload.deliver`

These fields are legacy-only. New cron creation should not depend on them.

## Job Categories

Use explicit branching:

- **Bound user automation**: `payload.kind == "agent_turn"` and
  `payload.session_key` is present. This uses the new session-turn model.
- **Legacy unbound automation**: user job with no `payload.session_key`. Keep the
  existing behavior. Do not migrate, infer, bind, or add UI for these jobs in
  this change.
- **System job**: `payload.kind == "system_event"` or known internal jobs such
  as `dream` / `heartbeat`. Keep their specialized paths.

The project should not grow a compatibility subsystem for legacy jobs. Missing
`session_key` means old behavior.

## New Job Creation

`CronTool` must create user automations with a `session_key`.

- If no request/session context exists, `cron action=add` should fail.
- Do not create new unbound jobs.
- Do not infer `session_key` from `channel/to` for new jobs.
- Remove `deliver` from the advertised tool schema. It can remain as a Python
  compatibility argument, but it must not affect new bound jobs.
- New bound jobs should persist `message` and `session_key`; legacy delivery
  fields should not be populated as part of the new path.

## Execution Path

Bound user automations should execute through `AgentLoop` as internal inbound
session events, not as an out-of-band `agent.process_direct()` call.

The intended flow is:

```text
cron due -> create automation inbound -> AgentLoop dispatches session turn
```

The inbound event should carry metadata identifying the automation, such as:

- job id
- job name
- run id
- prompt reference
- persisted trigger content

This keeps locking, runtime status, session persistence, and WebUI behavior on
the same path as normal chat turns.

`session_key` is the ownership anchor, but an `InboundMessage` still needs an
execution context. Bound cron must resolve `channel`, `chat_id`, and any
channel metadata from the target session/session metadata. It must not fall back
to legacy `payload.channel`, `payload.to`, or `payload.channel_meta` for bound
jobs. Those fields are only for the legacy unbound path.

The scheduler must not mark a bound job run as complete just because the inbound
event was queued. It should either wait for the automation turn to complete and
record the real outcome, or explicitly model the run as separate states such as
`queued` and `turn_completed`. A failed automation turn must be reflected in the
cron run record/job state, not hidden behind a successful enqueue.

## Active Session Behavior

Cron must not interrupt an active session turn.

- If the target session is idle, run the automation turn immediately.
- If the target session is running, defer the automation until the current turn
  completes.
- Do not inject the automation into the active turn's runtime context.
- Do not route automation messages into the existing mid-turn pending injection
  queue.
- UI/runtime status may show that an automation is queued, but the current LLM
  call should not see the queued automation.

Automation inbound events need explicit metadata, for example
`_automation_trigger` plus `_defer_until_session_idle`. `AgentLoop.run()` must
recognize that metadata before the existing `_pending_queues` mid-turn injection
branch. If the session is active, the event goes to a deferred automation queue,
not the pending injection queue.

The user experience goal is: cron can run after the current answer, but it
should not take over an answer already in progress.

## Session History

Do not persist the raw internal execution prompt as a normal user message.

Instead, persist a readable automation trigger event, for example:

```json
{
  "role": "user",
  "content": "Scheduled automation triggered: daily monitor\n\nCheck ...",
  "_automation_trigger": true,
  "automation_id": "abc123",
  "automation_name": "daily monitor",
  "automation_run_id": "abc123:1770000000000",
  "automation_prompt_ref": {
    "id": "cron.agent_turn.reminder",
    "version": 1,
    "sha256": "..."
  }
}
```

The assistant result should be saved as the normal assistant response for that
turn, with source metadata suitable for WebUI rendering.

This gives future turns useful context without leaking internal instruction text
into the transcript.

## Prompt Traceability

The rendered execution prompt should remain traceable, but it should not be part
of normal session history.

Use a named/versioned prompt reference in session history and save the full
rendered prompt in an internal run record.

Preferred direction:

- Move the cron execution prompt out of `commands.py` into a named template.
- Use a stable prompt id such as `cron.agent_turn.reminder`.
- Store `prompt_ref` and `automation_run_id` in session history.
- Store the full rendered prompt, prompt variables, and errors in an internal
  run record.

Avoid putting full prompt text into `jobs.json`; run records should not make the
cron store grow without bound.

## Visibility and Evaluation

A bound user automation is a real session turn.

- If it succeeds, save and publish the assistant response.
- Do not pass bound automation responses through `evaluate_response()`.
- Keep `evaluate_response()` only for system/legacy paths where the old behavior
  still applies.
- Avoid states where session history contains a response the user never saw.

If a bound automation starts executing, it must leave a visible closure in the
session:

- success response
- short failure message
- or an empty-result status message

Full exceptions and diagnostic details belong in the internal run record, not in
the user-facing transcript.

## Deleting Sessions

Deleting a session with bound automations should be a two-step operation.

Default delete behavior should block and return the associated automations:

```json
{
  "deleted": false,
  "blocked_by_automations": true,
  "automations": [
    {"id": "abc123", "name": "daily monitor", "enabled": true}
  ]
}
```

After explicit confirmation, the API may delete the bound user automations and
then delete the session/thread.

Rules:

- Only block on user-created bound jobs whose `payload.session_key` equals the
  session being deleted.
- Do not block on system jobs.
- Do not block on legacy unbound jobs.
- If the user manually deletes files outside the WebUI/API, do not try to
  compensate.

## WebUI Scope

This change should not grow into a full automation manager.

Keep the scope focused:

- Fix cron/session/memory semantics for new bound jobs.
- Preserve legacy job behavior.
- Add deletion protection for sessions with bound automations.
- Update the existing session automation panel only as needed for the new
  bound-job status.

Do not add deterministic legacy migration, legacy binding UI, or a global
calendar/task manager in this change.

## Manual Run

Do not add a user-visible "run now" feature as part of this design.

`CronService.run_job()` may remain an internal/test helper. It should not become
a product surface, and the implementation should avoid creating a separate
execution path that behaves differently from scheduled runs.

## Non-Goals

- No legacy migration.
- No automatic binding of legacy jobs.
- No runtime-context prompt asking the model to bind jobs.
- No new global automation manager.
- No new delivery-target abstraction.
- No user-visible manual cron run.
