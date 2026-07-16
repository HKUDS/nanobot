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

## Operating Rules

- For a create request, the next tool call after reading this skill should be
  `local_trigger(action="create", name="...")`. The current conversation route is injected
  automatically; do not query request context or inspect the workspace first. Derive a short name
  from the request when the user did not supply one. Specifically, do not call `my`, `find_files`,
  `list_dir`, or `exec` before `local_trigger`.
- When the `local_trigger` tool is registered, call it directly. Do not use shell commands such as
  `where`, `which`, or `nanobot --help`, inspect source, or check installed packages to decide
  whether the tool is usable. The CLI belongs to the later delivery environment, not discovery.
- After `create` succeeds, the nanobot-side setup is complete. Return the trigger ID, exact command,
  and ownership/security boundary without more tool calls. Inspect, write, install, start, or test an
  external watcher or adapter only when the user explicitly asks you to implement or test it.
- A request for an integration approach is not permission to deploy infrastructure. Explain the
  required bridge and ask for missing platform-specific details instead of guessing them. Do not
  invent a signature header or algorithm, or provide adapter code, until the event provider and its
  verification contract are known; a generic HMAC example is not a safe substitute.

## Create the Handoff

1. From the destination conversation, call `local_trigger(action="create", name="...")`.
2. Once `create` succeeds, treat its trigger ID and command as the handoff. A different `nanobot`
   executable may be a different installation and cannot confirm or invalidate this result.
3. Give the returned `nanobot trigger <id> "message"` command to the external event source. Replace
   `"message"` with the event payload; pipe stdin when content is generated or multiline.
4. Keep event detection, validation, authentication, and retry policy in that external component.
   Creating a trigger does not create a watcher or webhook service.

## Test the Handoff

Send a test delivery only from an environment known to use the same nanobot version and the same
workspace or config as the gateway. When multiple instances exist, make the target explicit with
`nanobot trigger --config <path> ...` or `nanobot trigger --workspace <path> ...`.

If a different executable reports that `trigger` is unavailable, that only describes that
installation; it does not invalidate the trigger returned by the tool. Keep the handoff and report
that delivery still needs testing with the gateway's runtime instead of retracting the result.

While a delivery is queued or running, the WebUI shows a bounded preview of the next payload rather
than the command placeholder.

## Connect Remote or Public Event Sources

The trigger store is local to the gateway workspace. Installing nanobot on a CI runner or another
host does not by itself share that store. Bridge remote events to the gateway host through SSH or an
authenticated adapter that invokes the command with the gateway's workspace or config. Prefer SSH
when no authenticated adapter already exists. A VPS, hosted runner, or cloud function may validate
an event, but it is not a complete bridge unless it also has an authenticated second hop to the
gateway host; it cannot invoke the workspace-local trigger directly. Name that second hop explicitly
in instructions and diagrams rather than drawing a remote adapter directly to the local command.

Authenticate and validate webhook or CI input before invoking the trigger. Never propose an HTTP
adapter that accepts arbitrary requests and calls the trigger: verify a signature, token, mTLS
identity, or equivalent first, using the provider's documented verification procedure. Allow only
intended events, bound the payload size, avoid shell interpolation, and make retries or duplicate
deliveries safe. Keep verification secrets in the adapter's environment or secret manager; do not
ask the user to paste them into chat or include them in the trigger command or payload. A local
trigger ID is not a public-webhook security boundary; never expose the raw command as an
unauthenticated endpoint.

Use `local_trigger(action="list")`, `enable`, `disable`, or `remove` tool calls for lifecycle
changes. These are agent tool actions, not `local_trigger ...` shell commands. Users can also manage
them in the WebUI Automations view. Lifecycle actions only affect the session-bound trigger; they do
not start or stop the external event source. The only external delivery CLI in this workflow is
`nanobot trigger <id> ...`.
