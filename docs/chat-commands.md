# In-Chat Commands

These commands work inside chat channels and interactive agent sessions:

| Command | Description |
|---------|-------------|
| `/new` | Stop current task and start a new conversation |
| `/stop` | Stop the current task |
| `/restart` | Restart the bot |
| `/status` | Show bot status |
| `/model` | Show the current model and available model presets |
| `/model <preset>` | Switch the runtime model preset for future turns |
| `/dream` | Run Dream memory consolidation now |
| `/dream-log` | Show the latest Dream memory change |
| `/dream-log <sha>` | Show a specific Dream memory change |
| `/dream-restore` | List recent Dream memory versions |
| `/dream-restore <sha>` | Restore memory to the state before a specific change |
| `/dream-prompt` | Show the current Dream prompt source |
| `/dream-prompt init` | Copy the bundled Dream prompt to `prompts/dream.md` for editing |
| `/skill` | List enabled skills and their descriptions |
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

The response shows the current model, the current preset, and the available preset names. Named presets come from the top-level `modelPresets` config and are the recommended way to configure model choices. `default` is always available and represents the model settings from direct `agents.defaults.*` fields.

To switch presets for future turns:

```text
/model fast
/model deep
/model default
```

Preset names come from the top-level `modelPresets` config. Switching is runtime-only: it does not rewrite `config.json`, and an in-progress turn keeps using the model it started with. See [Configuration: Model presets](./configuration.md#model-presets) for setup details.

## Periodic Tasks

Periodic tasks are driven by `HEARTBEAT.md` in your workspace (`~/.nanobot/workspace/HEARTBEAT.md`). When `nanobot gateway` starts, it registers a protected heartbeat cron job by default. Every 30 minutes, that job checks the file; if it finds tasks under `## Active Tasks`, the agent executes them and delivers results to your most recently active chat channel. If there are no active tasks, the heartbeat is skipped silently.

**Setup:** edit `~/.nanobot/workspace/HEARTBEAT.md` (created automatically by `nanobot onboard`):

```markdown
## Active Tasks

- Check weather forecast and send a summary
- Scan inbox for urgent emails
```

The agent can also manage this file itself — ask it to "add a periodic task" and it will update `HEARTBEAT.md` for you. Completed tasks should be deleted from the file, not moved to another section.

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
