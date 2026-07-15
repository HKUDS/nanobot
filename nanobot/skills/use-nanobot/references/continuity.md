# Continuity and Future Work

Use this reference when work outlives one tool call or starts later: long processes, delegation,
sustained goals, schedules, monitoring, events, or proactive delivery.

## Choose by Trigger and Lifetime

| Need | Primary mechanism | Important boundary |
|---|---|---|
| Run or interact with a command beyond one tool call | `exec` plus `write_stdin` | Preserve the exec session and poll it; it is not a durable service across gateway restarts. |
| Divide independent model work | `spawn` | Delegate bounded independent work, then merge and verify. |
| Continue an explicitly activated durable objective | `create_goal` / `update_goal` | Goal mutation is available only after a user `/goal` request. |
| Run an agent turn at a time or interval | `cron` | Each run is a model-backed agent instruction, not a shell-script scheduler. |
| Batch periodic agent checks and suppress routine delivery | `HEARTBEAT.md` | Heartbeat is still model-backed; quiet delivery does not make ordinary checks model-free. |
| React only after an external condition becomes actionable | External event source or cheap watcher plus `local_trigger` | Detection and filtering stay outside the agent; the trigger queues the useful turn. |
| Deliver proactively, cross-channel, or with a file | `message` | Reply normally in the current chat; use `message` for proactive or attachment delivery. |

## Keep Long Processes Recoverable

When a command remains active, retain its exec session ID and use `write_stdin` to poll, send
input, wait for an expected marker, close stdin, or terminate it. Use `list_exec_sessions` to
recover an ID after a context shift. Do not restart an expensive job merely because the initial
call yielded.

An exec session is suitable for an active development server, build, or interactive program
during the running gateway lifetime. If work must run for hours unattended, survive restarts,
or have operational ownership, install it under a real service, container, CI runner, or host
scheduler. Report its status command, logs/state location, restart behavior, and stop procedure.
Do not promise later notification unless a real delivery path is also established.

Treat an open-ended request to "monitor" or "watch" as persistent unless the user scopes it to
the current session. Do not default a permanent watcher to an exec sleep loop; use a recoverable
host runner and reserve exec sessions for temporary observation or setup verification.

## Use Parallelism and Goals for Their Real Semantics

Use `spawn` when investigations are independent enough to run concurrently and the main agent
can merge their results. Avoid delegation overhead for a small sequential task or when agents
would contend over the same files.

After an authorized `/goal` turn, create the durable objective before extended work, continue
through intermediate rounds, and call `update_goal` only when it is genuinely complete or meets
the defined blocked condition. Goal continuation is not a schedule, event source, or generic
permission to broaden the task.

## Separate Time-Based Agent Turns from Cheap Detection

Use `cron` when time itself should start an agent turn: a reminder, scheduled report, or
low-frequency task whose result should normally be delivered each run. Use heartbeat for a
maintained list of periodic agent checks where routine results should stay quiet.

Both cron and heartbeat invoke model-backed agent work. They are not zero-model polling engines
and cannot register or run a future shell script as their payload. When checks are frequent,
deterministic, already happen elsewhere, or must cost nothing until a change occurs, run the
detector in the source system, an OS scheduler, a service manager, a container, or CI, then use
a local trigger only for actionable output.

Once this external-detector route is selected, do not call or list nanobot `cron` or heartbeat
as setup, registration, delivery, or fallback. If a host crontab is appropriate, call it a host
crontab or OS scheduler so it cannot be confused with nanobot's model-backed cron tool.

## Build Event-Driven Monitoring

1. Prefer a source webhook, CI hook, filesystem watcher, or event stream when one exists.
2. Otherwise write the smallest polling adapter. It should fetch cheaply, compare persisted
   state, deduplicate, apply cooldowns, and emit only meaningful changes.
3. Use `local_trigger` with `action="create"` to bind an external entry point to the current
   conversation. It returns the exact `nanobot trigger ...` delivery command; the user does not
   need to run `/trigger` first when this tool is available.
4. Put that command in the source system or invoke it from the adapter only after the condition
   matches. Pipe long content through stdin rather than forcing it into a shell argument.
5. Run the adapter with infrastructure appropriate to its lifetime and test one synthetic event
   end to end.
6. Report the adapter location, persisted state, trigger binding, delivery target, status check,
   and stop/removal procedure.

The gateway and sender must use the same nanobot workspace/config. Local trigger delivery is
durable and at-least-once, so downstream actions should tolerate duplicates. A local trigger is
a session-bound CLI entry point, not a built-in public webhook. If a third party requires HTTP,
use its existing adapter or run a small authenticated receiver that invokes the CLI; do not
invent a gateway webhook URL.

If `local_trigger` is absent, prepare all safe artifacts first, then ask the user to run
`/trigger <name>` in the target chat and return the generated command. This is a fallback, not
the normal UX. Use local trigger list/enable/disable/remove for bindings in the current
conversation, and manage the external watcher separately.

Future output needs an explicit bridge. If an existing command will produce useful output later,
wrap or pipe that future invocation into the local trigger command. Running it once during setup
does not connect an unrelated future process to the conversation.
