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
| `/help` | Show available in-chat commands |

## Model Presets

Use `/model` to inspect the current runtime model:

```text
/model
```

The response shows the current model, the current preset, and the available preset names. `default` is always available and represents the model settings from `agents.defaults.*`.

To switch presets for future turns:

```text
/model fast
/model deep
/model default
```

Preset names come from the top-level `modelPresets` config. Switching is runtime-only: it does not rewrite `config.json`, and an in-progress turn keeps using the model it started with. See [Configuration: Model presets](./configuration.md#model-presets) for setup details.

## Periodic Tasks

The gateway wakes up every 30 minutes and checks `HEARTBEAT.md` in your workspace (`~/.nanobot/workspace/HEARTBEAT.md`). If the file has tasks, the agent executes them and delivers results to your most recently active chat channel.

**Setup:** edit `~/.nanobot/workspace/HEARTBEAT.md` (created automatically by `nanobot onboard`):

```markdown
## Periodic Tasks

- [ ] Check weather forecast and send a summary
- [ ] Scan inbox for urgent emails
```

The agent can also manage this file itself — ask it to "add a periodic task" and it will update `HEARTBEAT.md` for you.

> **Note:** The gateway must be running (`nanobot gateway`) and you must have chatted with the bot at least once so it knows which channel to deliver to.
