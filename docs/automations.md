# Automations

<!-- Meta description: Create, run, and manage nanobot scheduled automations, local triggers, and heartbeat-backed background checks. -->

Automations are agent turns that run later in a linked topic. Use them when nanobot should do work without someone actively typing: reminders, recurring checks, nightly summaries, CI follow-ups, local script reports, or webhook-driven events.

Create automations from the chat channel or WebUI topic where the result should appear. That lets nanobot keep the right session history, workspace, and reply target.

## Choose an Automation Type

| Type | Starts from | Best for | Created with |
|---|---|---|---|
| Scheduled automation | Time, interval, or cron expression | Recurring reminders, scheduled summaries, one-time future tasks | Ask nanobot in the target topic to schedule it with the `cron` tool |
| Local trigger | A local `nanobot trigger ...` command | CI jobs, webhooks, shell scripts, generated reports | `/trigger <name>` in the target topic |
| Heartbeat | Protected system schedule | Quiet recurring checks that should only report useful results | Edit `<workspace>/HEARTBEAT.md` |

The two user-created automation types are scheduled automations and local triggers. Heartbeat uses the same background service but is system-managed and protected from normal automation edits.

## Before You Create One

Keep the gateway running. Your WebUI or TUI already uses one; you do not need a second gateway. To keep it alive after closing interactive launchers, run `nanobot gateway --background` with the same instance selectors, or use `/detach` in the TUI. The gateway owns background delivery for chat apps, WebUI topics, scheduled automations, local triggers, heartbeat, and Dream jobs.

Use the same workspace and config for the gateway and any process that sends local trigger messages. If you run multiple nanobot instances, pass the matching `--config` or `--workspace` option to `nanobot trigger`.

Create each automation from the target topic. An automation without a linked topic cannot be enabled or run from the WebUI because nanobot would not know where to deliver the turn.

## Scheduled Automations

Scheduled automations are created by the agent's `cron` tool. In practice, ask nanobot from the target chat or WebUI topic:

```text
Every weekday at 9am, check open pull requests and summarize blockers here.
```

or:

```text
Tomorrow at 4pm, remind me to send the release notes.
```

The cron tool supports interval schedules, cron expressions, and one-time scheduled tasks. Cron expressions can include an IANA timezone such as `America/Vancouver`; otherwise nanobot uses the runtime default timezone.

Scheduled automations normally deliver the result back to the session where they were created. Use them for work that should run on a predictable schedule and report each run.

Write what the task should do, such as "Remind me to drink water". nanobot sends the final reply to the task's saved chat. You do not need to put a channel, chat ID, or a `message` tool call in the instructions for that reply.

For separate sends, specify the recipients in the instructions. The agent can still use `message` to send to other chats, send to several recipients, or attach files. Existing tasks that explicitly request this tool remain supported.

Writing "send to WhatsApp" in a task's instructions does not change its saved chat. If you create
the task in a WebUI chat, its normal reply still returns there. A separate WhatsApp send requires
the agent to call `message` with that destination. To make WhatsApp the normal reply destination,
create the task in that WhatsApp chat, or change its saved chat in Automations.

### Scheduled Result Delivery

Task completion and message delivery are separate. `Turn completed` and a successful task run
mean that execution finished. They do not confirm that a chat service received the result.

The gateway saves final scheduled messages before it accepts them into the outgoing queue.
This includes explicit `message` calls in existing tasks. Each recipient has a separate delivery
record. Progress, reasoning, and streaming events do not enter this queue. WebUI streaming and
saved chat history keep their existing behavior.
The queue cannot recover a send that the agent never requested. If an expected recipient has no
delivery record, check the task's saved chat and the run's `message` tool calls first.
External channels receive one final scheduled reply instead of a streamed reply. Ordinary chat
streaming is unchanged.

If a channel reports that it has not sent any part of a message, the gateway retries every
30 seconds, for up to one hour after queue acceptance. It sends the saved message to the saved
destination. It does not run the task or call the model again. A gateway restart resumes pending
messages. Deleting or resetting the source chat cancels pending messages from that chat generation.
Disabling a channel prevents its pending messages from being sent. Changing a task's chat affects
future runs; it does not redirect an already queued result.

If a request times out after sending starts, or the gateway stops during a send, delivery is
unknown. The gateway does not retry that message automatically: the service might already have
accepted it. Check the destination before sending the result again. This is not an exactly-once
delivery guarantee. Adapter or service-specific retries still follow their own protocol.

Look for `Channel delivery` in the gateway log. The run ID links execution to each delivery ID:

| Status | Meaning |
|---|---|
| `pending` | Saved locally; waiting for an attempt or a channel connection |
| `sent` | The channel adapter completed its send; not a recipient read receipt |
| `failed` | Not sent: expired, disabled channel, replaced source chat, or rejected destination/policy |
| `unknown` | An interrupted or failed attempt might have reached the service; no automatic retry |

The queue is stored in `delivery/outbox.sqlite3`, beside the active config file. Include this
directory in instance backups; stop the gateway before copying it. It holds at most 256 pending messages, with a 1 MiB serialized limit
per message. A full queue or storage error rejects the enqueue operation instead of reporting it
as accepted. Terminal records discard message text and keep status for up to seven days, capped
at 1,000 records. Existing job and session files are not converted. Older versions ignore this
queue; pending delivery resumes only when a version with queue support runs again.

For background checks that should stay quiet unless there is something useful to report, use heartbeat instead of a user-created scheduled automation.

Repetition alone does not select heartbeat. "Every day at 8am, remind me to drink water" needs a cron schedule. "Keep an eye on open issues and tell me when one needs attention" can use heartbeat if the check time is flexible. Heartbeat does not guarantee a requested time or interval.

An upgrade does not overwrite your workspace's `AGENTS.md` or convert existing heartbeat entries into cron jobs. The current scheduling rules are included in the system prompt. If an old workspace rule directs all recurring tasks to heartbeat, update that rule too. To correct an existing reminder, remove its old heartbeat entry and create the cron task once. Check the task list to avoid duplicates.

## Local Triggers

Local triggers let a local script or external service send a message into a specific nanobot session later.

Create the trigger from the chat or WebUI topic where future messages should arrive:

```text
/trigger PR review
```

nanobot replies with a trigger ID and a command shaped like:

```bash
nanobot trigger trg_8K4P2Q9X "Review PR #4502"
```

Replace the quoted text with the message nanobot should receive. For generated or longer content, pipe stdin:

```bash
generate-report | nanobot trigger trg_8K4P2Q9X
```

For multiple instances, use the same config or workspace selector as the gateway:

```bash
nanobot trigger --config ./bot-a/config.json trg_8K4P2Q9X "Nightly report"
nanobot trigger --workspace ./bot-a/workspace trg_8K4P2Q9X "Nightly report"
```

nanobot does not provide a built-in public webhook receiver for local triggers. If GitHub, CI, or another external system should wake nanobot, run your own small webhook service and have it call `nanobot trigger` after it builds the final message.

## Heartbeat

Heartbeat is for recurring workspace checks that should usually stay quiet. It reads `<workspace>/HEARTBEAT.md`, executes active tasks, and sends only useful or actionable results to the most recently active chat target.

Use heartbeat for checks such as "watch this repo for important failures" or "periodically inspect this workspace and only tell me when action is needed." Use a scheduled automation instead when every run should produce a visible reminder or report.

Heartbeat is enabled by default when `nanobot gateway` starts. Configure it in [`configuration.md#gateway-heartbeat`](./configuration.md#gateway-heartbeat).

## Manage Automations

Use the WebUI Automations view to:

- filter by all, active, paused, needs-attention, or system jobs;
- search by task name, message, trigger command, linked topic, schedule, or status;
- sort by next run, last run, updated time, or name;
- run scheduled automations now;
- pause or resume, rename, or delete user-created automations;
- copy the CLI command for local triggers;
- inspect protected system automations without changing them.

Local triggers do not have a WebUI "Run now" action because each run needs a message. Copy the `nanobot trigger ...` command from the WebUI and replace `"message"` with the content that should be delivered.

### Change the Chat for a Scheduled Task

Open a scheduled task in **Automations**. **Run and reply in** shows its saved chat, with the channel logo and name. WebUI chats use the same display names as the sidebar. A renamed chat keeps its identity and task binding. Chats with the same name show an `@handle` to help you tell them apart.

To change the chat:

1. Select another chat from **Run and reply in**.
2. Review the task instructions, which are read-only by default. If they need changes, select **Edit instructions**. Remove recipients you no longer want, but keep intended separate sends. Members of the new chat can see future task messages and results.
3. Select **Confirm change**. Wait for the saved confirmation.

If you edit the instructions, the button becomes **Save and change**. Both changes are saved together; nothing is saved when you select **Edit instructions**. To change the task name or schedule, use **Edit** in the task details instead.

Select **Cancel** before saving to return to the task without changes. After a successful save, select **Change back to** to review a return to the previous chat. You must confirm this change too. You can also select a previous chat from the list later. This changes future runs; it does not recall messages already sent.

Future runs use the new chat's history and reply there by default. Previous messages stay in their original chat. Previous run results remain available. Changing the chat does not run the task, enable it, or change its schedule.

You can discuss each new result in that same chat. Background task results also return there. If you delete that chat, nanobot asks you to confirm deletion of its scheduled tasks as well. Cancelling the deletion keeps the chat and tasks.

The list contains existing chats on the same gateway with the same effective workspace and access mode. Chat-app targets need a running channel and a saved reply route from an earlier incoming message. If a chat is missing, send nanobot a message there and check that its channel is running. Raw recipient IDs, cross-host moves, unified sessions, system jobs, and local triggers are not supported by this selector. An older gateway keeps the existing read-only view.

If a scheduled turn is running or queued, wait for it to finish before changing the chat. The current scheduler also rejects a change while another scheduled turn is active. If another editor changes the task, reopen the task and review the latest instructions. A rejected save leaves the draft visible.

This changes the whole task chat, not a separate forwarding address. Explicit `message` tool instructions can still send elsewhere. Shared workspace files and memory remain shared; changing the chat does not create a new security boundary. The confirmation screen lets you edit instructions such as "send to the original chat" before you save. nanobot does not silently rewrite those instructions.

### Back Up Before Downgrading

Chat changes store a binding version and the session used by each previous run. Existing jobs do not need a manual migration when upgrading. Older nanobot versions can discard these new fields when they write the cron store. After a chat change, that can make old run results unavailable in the WebUI and remove protection against stale CLI updates.

Before trying this feature, stop the gateway and other cron writers, then back up the complete `cron/` directory in the configured agent workspace (`~/.nanobot/workspace/cron/` by default), including `jobs.json` and `runs/`. For a downgrade after changing a chat, stop those processes again and restore that coherent pre-change cron backup. This also restores the old schedules and task settings; later changes are not included. Chat messages are not moved or deleted.

## Delivery and Reliability

Automation storage and queue delivery belong to the gateway's configured agent workspace. Scheduled and triggered turns linked to WebUI/TUI chats use the chat's saved project context and access mode; chat-app turns use the gateway's configured workspace. The selected project can differ from the agent workspace that stores jobs, memory, and queues. Starting the TUI inside a project selects that project for the chat but does not by itself create a separate gateway instance. Select the matching configured agent workspace when invoking `nanobot trigger --workspace`, not merely the project directory. See [Multiple Instances](multiple-instances.md) when these need to be separate.

Schedules do not replay missed occurrences after a gateway restart:

| Schedule | Behavior after restart |
|---|---|
| One-time (`at`) | A time already in the past has no next run and is not automatically executed. Review the task and run it manually or create a replacement. |
| Interval (`every`) | The next run is one full interval after restart; missed intervals are not replayed. |
| Cron expression | The next matching time after restart is used; missed matches are not replayed. |

Intervals are also recalculated after a run finishes, so a long-running task can shift its next interval. Use a cron expression for wall-clock scheduling, and keep the host awake and gateway running when timing matters. These rules concern scheduled jobs; queued local trigger messages have the separate recovery behavior below.

Local trigger messages are written to a durable queue. If the gateway is not running yet, the message waits in that workspace. If the linked topic is already running a turn, the trigger waits until the session becomes idle instead of being injected into the active turn.

The local trigger queue is at-least-once, not exactly-once. If the gateway exits after claiming a delivery but before the linked turn completes, the next gateway start requeues that delivery. External scripts should make repeated trigger messages safe. If the delivery reaches the agent and the turn fails, the delivery is marked failed instead of retrying forever.

Each local trigger delivery writes an audit record under `<workspace>/triggers/runs`. Run one gateway consumer per workspace; the local queue is not a distributed multi-consumer queue.

## Common Patterns

For a nightly report, ask from the target topic:

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

If an automation does not run, check that `nanobot gateway` is running, the automation is enabled, and it was created from a linked topic.

If a local trigger waits forever, confirm the command uses the same workspace or config as the gateway.

If a trigger message appears twice after a restart, treat it as expected at-least-once delivery and make the external message idempotent.

If you need to edit, pause, resume, rename, delete, or inspect automations, use the WebUI Automations view.

## Related Docs

- [`webui.md#automations`](./webui.md#automations) for the browser management view
- [`chat-commands.md#local-triggers`](./chat-commands.md#local-triggers) for `/trigger`
- [`cli-reference.md#local-triggers`](./cli-reference.md#local-triggers) for `nanobot trigger`
- [`configuration.md#gateway-heartbeat`](./configuration.md#gateway-heartbeat) for heartbeat settings
- [`guides/long-running-ai-agent.md`](./guides/long-running-ai-agent.md) for long-running agent work
