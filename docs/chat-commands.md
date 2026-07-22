# In-Chat Commands

These commands work inside chat channels and interactive agent sessions:

| Command | Description |
|---------|-------------|
| `/new` | Stop current task and start a new conversation |
| `/stop` | Stop the current task |
| `/restart` | Restart the bot |
| `/status` | Show bot status |
| `/model` | Show the current model and available model presets |
| `/model <preset>` | Switch and persist the model preset for the current session |
| `/dream` | Run Dream memory consolidation now |
| `/dream-log` | Show the latest Dream memory change |
| `/dream-log <sha>` | Show a specific Dream memory change |
| `/dream-restore` | List recent Dream memory versions |
| `/dream-restore <sha>` | Restore memory to the state before a specific change |
| `/dream-prompt` | Show how Dream is being guided for memory |
| `/dream-prompt init` | Create an editable Dream memory guide at `prompts/dream.md` |
| `/skill` | List enabled skills and their descriptions |
| `/trigger` | Show local trigger usage |
| `/trigger <name>` | Create a named local trigger for the current chat/session |
| `/pairing` | List pending pairing requests |
| `/pairing approve <code>` | Approve a pairing code |
| `/pairing deny <code>` | Deny a pending pairing request |
| `/pairing revoke <user_id>` | Revoke a previously approved user on the current channel |
| `/pairing revoke <channel> <user_id>` | Revoke a previously approved user on a specific channel |
| `/help` | Show available in-chat commands |

## Pairing

When someone sends a DM to the bot and isn't on the allowlist — whether it's a new user or an existing user on a new channel — nanobot automatically replies with a **pairing code** (like `ABCD-EFGH`) that expires in 10 minutes. To grant them access:

```text
/pairing approve ABCD-EFGH
```

To see who's waiting, use `/pairing`. To remove someone later, use `/pairing revoke <user_id>` — you can find user IDs in the `/pairing list` output.

See [Configuration: Pairing](./configuration.md#pairing) for the full setup guide.

## Model Presets

Use `/model` to inspect the current runtime model:

```text
/model
```

The response shows the current session's model and preset, plus the available preset names. Named presets come from the top-level `modelPresets` config and are the recommended way to configure model choices. `default` is always available and represents the model settings from direct `agents.defaults.*` fields.

To switch presets for future turns:

```text
/model fast
/model deep
/model default
```

Preset names come from the top-level `modelPresets` config. Switching affects only the current session and persists the selection in that session, so later turns keep using it across process restarts. It does not rewrite `config.json`, does not change other sessions, and does not alter an in-progress turn's captured model. Sessions without a saved selection follow `agents.defaults.modelPreset` (or the implicit `default` preset when it is omitted). See [Configuration: Model presets](./configuration.md#model-presets) for setup details.

## Local triggers

Use `/trigger <name>` when a local script or another service should be able to
send a message into the current chat/session later. A name is required; plain
`/trigger` only shows the usage hint.

Create the trigger from the chat where future messages should arrive:

```text
/trigger PR review
```

nanobot replies with a trigger ID and a command shaped like:

```bash
nanobot trigger trg_8K4P2Q9X "Review PR #4502"
```

Replace `"Review PR #4502"` with the message you want nanobot to receive. The
trigger is bound to the session where it was created, so the message goes back
to that same chat. Keep `nanobot gateway` running so trigger messages can be
delivered. The trigger message starts an automation turn recorded in that
session with the message you passed to the CLI; it is not treated as a normal
user message. If that session is already running a turn, the trigger waits
until the session is idle instead of being injected into the active turn.

Trigger deliveries are stored in the workspace until their linked agent turn
finishes successfully. If the gateway exits after claiming a delivery but before
the turn completes, the next gateway start requeues that delivery. This is an
at-least-once local queue: a delivery may run more than once if the process
exits at the wrong time, so external scripts should make repeated trigger
messages safe. If the delivery reaches the agent and the agent turn fails, the
delivery is marked failed in Automations instead of retrying forever.

For longer or generated content, omit the message argument and pipe stdin:

```bash
printf '%s\n' "Review the latest failed CI job" | nanobot trigger trg_8K4P2Q9X
```

If an external webhook should wake nanobot up, run your own small webhook
service and have it call the trigger command after it builds the final message:

```bash
nanobot trigger <trigger-id> "<message>"
```

If you run multiple nanobot instances, pass the same config or workspace
selector used by the gateway:

```bash
nanobot trigger --config ./bot-a/config.json trg_8K4P2Q9X "Nightly report"
nanobot trigger --workspace ./bot-a/workspace trg_8K4P2Q9X "Nightly report"
```

Manage triggers from the WebUI Automations view. You can search, pause/resume,
rename, delete, and copy the trigger command there. A session may have multiple
triggers, just like it may have multiple scheduled automations.

See [Automations](./automations.md) for how local triggers fit with scheduled
automations, heartbeat, and gateway delivery.

## Periodic Tasks

Periodic background checks are driven by `HEARTBEAT.md` in your workspace (`~/.nanobot/workspace/HEARTBEAT.md`). When `nanobot gateway` starts, it registers a protected heartbeat cron job by default. Every 30 minutes, that job checks the file; if it finds tasks under `## Active Tasks`, the agent executes them and delivers only results that pass the notification gate to your most recently active chat channel. If there are no active tasks, or the result is routine with nothing useful to report, the heartbeat is skipped silently.

Use heartbeat for recurring checks that should usually stay quiet. User-created cron jobs are different: they run as scheduled turns in the chat/session where they were created and normally deliver the result back to that channel.

**Setup:** edit `~/.nanobot/workspace/HEARTBEAT.md` (created automatically by `nanobot onboard`):

```markdown
## Active Tasks

- Check weather forecast and notify me only if storms are expected
- Scan inbox for urgent emails and notify me if any are found
```

The agent can also manage this file itself - ask it to "add a periodic background check" or "check this periodically but only notify me if something changes" and it will update `HEARTBEAT.md` for you. Completed tasks should be deleted from the file, not moved to another section.

You can change the interval or disable the built-in heartbeat in `~/.nanobot/config.json`:

```json
{
  "gateway": {
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  }
}
```

The heartbeat job is visible in `cron(action="list")` as `heartbeat`, but it is system-managed and cannot be removed with the `cron` tool. To stop it, set `gateway.heartbeat.enabled` to `false` and restart the gateway.

> **Note:** The gateway must be running (`nanobot gateway`) and you must have chatted with the bot at least once so it knows which channel to deliver to.
