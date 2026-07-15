---
name: local-trigger
description: Connect an external event source to the current conversation so it can wake nanobot with a message. Use for local watchers, webhooks, CI, or other event-driven handoffs; not for schedules or polling.
---

# Local Trigger

Use a local trigger when something outside nanobot detects an event and should start an agent turn
in this conversation. The trigger is the delivery edge only: it does not watch, poll, schedule, or
host a public webhook.

Choose the primitive by what starts the work:

- Use `local_trigger` for an external event such as a file watcher, CI job, or webhook adapter.
- Use `cron` when time starts every run and every run should execute an agent instruction.
- Use heartbeat for recurring checks that should stay quiet when there is nothing useful to report.

## Create the Handoff

1. From the destination conversation, call `local_trigger(action="create", name="...")`.
2. Give the returned `nanobot trigger <id> "message"` command to the external event source. Replace
   `"message"` with the event payload; pipe stdin when content is generated or multiline.
3. Keep event detection, validation, authentication, and retry policy in that external component.
4. Send a test delivery and verify that the turn arrives in the same conversation. While a delivery
   is queued or running, the WebUI shows a bounded preview of the next payload rather than the
   command placeholder.

The external command must use the same nanobot workspace or config as the gateway. A local trigger
ID is not a public-webhook security boundary; do not expose a raw trigger command to untrusted
callers.

Use `list`, `enable`, `disable`, or `remove` for lifecycle changes. These actions only affect the
session-bound trigger; they do not start or stop the external event source.
