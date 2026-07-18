# Automations

<!-- Meta description: Create, run, and manage nanobot scheduled automations, local triggers, and heartbeat-backed background checks. -->

Automations are agent turns that run later in a linked chat/session. Use them
when nanobot should do work without someone actively typing: reminders,
recurring checks, nightly summaries, CI follow-ups, local script reports, or
webhook-driven events.

Create automations from the chat, channel, or WebUI session where the result
should appear. That lets nanobot keep the right session history, workspace, and
reply target.

## Choose an Automation Type

| Type | Starts from | Best for | Created with |
|---|---|---|---|
| Scheduled automation | Time, interval, or cron expression | Recurring reminders, scheduled summaries, one-time future tasks | Ask nanobot in the target session to schedule it with the `cron` tool |
| Local trigger | A local `nanobot trigger ...` command | CI jobs, webhooks, shell scripts, generated reports | `/trigger <name>` in the target session |
| Heartbeat | Protected system schedule | Quiet recurring checks that should only report useful results | Edit `<workspace>/HEARTBEAT.md` |

The two user-created automation types are scheduled automations and local
triggers. Heartbeat uses the same background service but is system-managed and
protected from normal automation edits.

## Before You Create One

Keep `nanobot gateway` running. The gateway owns background delivery for chat
apps, WebUI sessions, scheduled automations, local triggers, heartbeat, and
Dream jobs.

Use the same workspace and config for the gateway and any process that sends
local trigger messages. If you run multiple nanobot instances, pass the matching
`--config` or `--workspace` option to `nanobot trigger`.

Local trigger state lives in that workspace. Installing nanobot on a CI runner
or another host does not connect it to the gateway's trigger store. Bridge a
remote event to the gateway host with SSH or a trusted adapter that invokes the
command against the gateway's workspace or config. A cloud function or hosted
runner is not a complete bridge by itself; it still needs an authenticated
second hop to the gateway host.

Create each automation from the target session. An automation without a linked
chat/session cannot be enabled or run from the WebUI because nanobot would not
know where to deliver the turn.

## Scheduled Automations

Scheduled automations are created by the agent's `cron` tool. In practice, ask
nanobot from the target chat or WebUI session:

```text
Every weekday at 9am, check open pull requests and summarize blockers here.
```

or:

```text
Tomorrow at 4pm, remind me to send the release notes.
```

The cron tool supports interval schedules, cron expressions, and one-time
scheduled tasks. Cron expressions can include an IANA timezone such as
`America/Vancouver`; otherwise nanobot uses the runtime default timezone.

Scheduled automations normally deliver the result back to the session where they
were created. Use them for work that should run on a predictable schedule and
report each run.

For background checks that should stay quiet unless there is something useful to
report, use heartbeat instead of a user-created scheduled automation.

## Local Triggers

Local triggers let a local script or external service send a message into a
specific nanobot session later.

Ask nanobot to create the trigger from the chat or WebUI session where future
messages should arrive. When the gateway trigger service is available, the
agent can create the session binding and return the delivery command directly.
The successful tool result is the handoff: test the returned command with the
gateway's nanobot runtime instead of probing another `nanobot` installation.

You can also create one manually with the chat command:

```text
/trigger PR review
```

nanobot replies with a trigger ID and a command shaped like:

```bash
nanobot trigger trg_8K4P2Q9X "Review PR #4502"
```

Replace the quoted text with the message nanobot should receive. For generated
or longer content, pipe stdin:

```bash
generate-report | nanobot trigger trg_8K4P2Q9X
```

For multiple instances, use the same config or workspace selector as the
gateway:

```bash
nanobot trigger --config ./bot-a/config.json trg_8K4P2Q9X "Nightly report"
nanobot trigger --workspace ./bot-a/workspace trg_8K4P2Q9X "Nightly report"
```

nanobot does not provide a built-in public webhook receiver for local triggers.
If GitHub, CI, or another external system should wake nanobot, run your own
small webhook service and have it call `nanobot trigger` after it builds the
final message. Authenticate and validate the request before invoking the CLI,
allow only intended events, bound the payload size, and make duplicate delivery
safe. A trigger ID or raw trigger command is not authentication and must not be
exposed as an unauthenticated public endpoint. Store verification secrets in
the adapter's environment or secret manager, not in the trigger command,
payload, or chat. Follow the event provider's documented signature algorithm;
do not substitute a generic HMAC example for provider-specific verification.

The agent can list, pause, resume, or remove triggers bound to the current
conversation. The WebUI Automations view provides the same lifecycle controls
across the workspace. Neither control surface starts or stops the external
script or service that invokes the trigger; manage that component separately.

While a delivery is queued or running, the WebUI shows a bounded preview of the
next message that will be delivered. Previews include up to 4,000 characters;
longer payloads end with a truncation marker while the full message remains in
the delivery queue. The `"message"` text in the copied command remains only a
placeholder to replace at invocation time. If several messages are waiting for
one trigger, the in-flight message is shown first, followed by the oldest queued
message after it completes.

## Heartbeat

Heartbeat is for recurring workspace checks that should usually stay quiet. It
reads `<workspace>/HEARTBEAT.md`, executes active tasks, and sends only useful or
actionable results to the most recently active chat target.

Use heartbeat for checks such as "watch this repo for important failures" or
"periodically inspect this workspace and only tell me when action is needed." Use
a scheduled automation instead when every run should produce a visible reminder
or report.

Heartbeat is enabled by default when `nanobot gateway` starts. Configure it in
[`configuration.md#gateway-heartbeat`](./configuration.md#gateway-heartbeat).

## Manage Automations

Use the WebUI Automations view to:

- filter by all, active, paused, needs-attention, or system jobs;
- search by task name, message, trigger command, linked chat, schedule, or
  status;
- sort by next run, last run, updated time, or name;
- run scheduled automations now;
- pause or resume, rename, or delete user-created automations;
- copy the CLI command for local triggers;
- inspect protected system automations without changing them.

Local triggers do not have a WebUI "Run now" action because each run needs a
message. Copy the `nanobot trigger ...` command from the WebUI and replace
`"message"` with the content that should be delivered.

## Delivery and Reliability

Automation delivery is workspace-local. Scheduled jobs and local trigger
deliveries use the same workspace as the gateway.

Local trigger messages are written to a durable queue. If the gateway is not
running yet, the message waits in that workspace. If the linked session is
already running a turn, the trigger waits until the session becomes idle instead
of being injected into the active turn.

The local trigger queue is at-least-once, not exactly-once. If the gateway exits
after claiming a delivery but before the linked turn completes, the next gateway
start requeues that delivery. External scripts should make repeated trigger
messages safe. If the delivery reaches the agent and the turn fails, the
delivery is marked failed instead of retrying forever.

Each local trigger delivery writes an audit record under
`<workspace>/triggers/runs`. Run one gateway consumer per workspace; the local
queue is not a distributed multi-consumer queue.

## Common Patterns

For a nightly report, ask from the target session:

```text
Every night at 9pm, review today's workspace changes and summarize anything I should handle tomorrow.
```

For a CI follow-up, create a trigger once:

```text
/trigger CI follow-up
```

Then have your CI or webhook adapter call:

```bash
nanobot trigger <trigger-id> "Build failed on main. Inspect the logs and suggest the next fix."
```

For a local report script:

```bash
generate-report | nanobot trigger <trigger-id>
```

## Troubleshooting

If an automation does not run, check that `nanobot gateway` is running, the
automation is enabled, and it was created from a linked chat/session.

If a local trigger waits forever, confirm the command uses the same workspace or
config as the gateway.

If a trigger message appears twice after a restart, treat it as expected
at-least-once delivery and make the external message idempotent.

If you need to edit, pause, resume, rename, delete, or inspect automations, use
the WebUI Automations view.

## Related Docs

- [`webui.md#automations`](./webui.md#automations) for the browser management view
- [`chat-commands.md#local-triggers`](./chat-commands.md#local-triggers) for `/trigger`
- [`cli-reference.md#local-triggers`](./cli-reference.md#local-triggers) for `nanobot trigger`
- [`configuration.md#gateway-heartbeat`](./configuration.md#gateway-heartbeat) for heartbeat settings
- [`guides/long-running-ai-agent.md`](./guides/long-running-ai-agent.md) for long-running agent work
