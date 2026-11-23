# In-Chat Commands

Use these slash commands inside the WebUI, terminal chat, or connected chat apps:

| Command | Description |
|---------|-------------|
| `/new` | Stop the current task and start a new conversation |
| `/compact` | Summarize the current conversation context while keeping saved chat history |
| `/stop` | Stop the current task without cancelling its saved goal |
| `/goal <task>` | Start a sustained goal for this conversation |
| `/cancel_goal` | Cancel the active or blocked goal (also stops work on an active goal) |
| `/restart` | Restart the bot |
| `/status` | Show bot status |
| `/model` | Show the current model and available model presets |
| `/model <preset>` | Switch and save the model preset for this conversation |
| `/dream` | Run Dream memory consolidation now |
| `/dream-log` | Show the latest Dream memory change |
| `/dream-log <sha>` | Show a specific Dream memory change |
| `/dream-restore` | List recent Dream memory versions |
| `/dream-restore <sha>` | Restore memory to the state before a specific change |
| `/dream-prompt` | Show how Dream is guided for memory |
| `/dream-prompt init` | Create an editable Dream guide at `prompts/dream.md` |
| `/skill` | List enabled skills and their descriptions |
| `/trigger <name>` | Create a named local trigger for the current chat |
| `/pairing` | List pending pairing requests |
| `/pairing approve <code>` | Approve a pairing code |
| `/pairing deny <code>` | Deny a pending pairing request |
| `/pairing revoke <user_id>` | Revoke an approved user on the current channel |
| `/pairing revoke <channel> <user_id>` | Revoke an approved user on a specific channel |
| `/help` | Show available commands |

## Commands and File Paths

Only recognized command names (case-insensitive) are handled as commands. Anything else—including file paths like `/tmp` or `/Users/alice/report.md`—is sent to the agent normally. If a folder happens to match a command name (like `/new`), add a trailing slash (`/new/`) or write it in a sentence (`Look at /new`).

In the WebUI, recognized commands run immediately even while a reply is in progress (so `/stop` does not wait in the queue).

## Pairing

When an unapproved user sends a DM on a pairing-enabled chat app, nanobot replies with a short **pairing code** (such as `ABCD-EFGH`) that expires in 10 minutes. Approve them from any authorized chat or in the WebUI:

```text
/pairing approve ABCD-EFGH
```

Use `/pairing` to see pending requests and `/pairing revoke <user_id>` to remove access later. See [Configuration: Pairing](./configuration.md#pairing) for setup options.

## Model Presets

Run `/model` to see your active model and available presets, or switch presets for the current conversation:

```text
/model fast
/model deep
/model default
```

Switching persists for future turns in this conversation (even across restarts) without affecting other conversations or interrupting a reply in progress. To add presets, open **Settings → Models** or see [Configuration: Model presets](./configuration.md#model-presets).

## Goals

Use `/goal <task>` to start a sustained goal. Only you can cancel a goal—either run `/cancel_goal` or expand the goal in the WebUI and click **Cancel goal**. Cancelling an active goal stops its work while keeping chat history; cancelling a blocked goal leaves unrelated replies running.

## Local Triggers

Create a local trigger inside the chat where future messages should appear:

```text
/trigger PR review
```

nanobot replies with a trigger ID and CLI command:

```bash
nanobot trigger trg_8K4P2Q9X "Review PR #4502"
```

You can also pipe longer content from a script:

```bash
printf '%s\n' "Review the latest failed CI job" | nanobot trigger trg_8K4P2Q9X
```

For multiple instances, pass the same `--config` or `--workspace` used by the running gateway. Keep `nanobot gateway` running so trigger messages can be delivered. Manage existing triggers in the WebUI **Automations** view, and see [Automations](./automations.md) for delivery behavior and examples.

## Periodic Tasks (Heartbeat)

Heartbeat runs quiet background checks from `~/.nanobot/workspace/HEARTBEAT.md` every 30 minutes while `nanobot gateway` is running, and only messages you when something needs attention. Add tasks under `## Active Tasks` (or ask nanobot to add one for you):

```markdown
## Active Tasks

- Check weather forecast and notify me only if storms are expected
- Scan inbox for urgent emails and notify me if any are found
```

Remove completed tasks from the file when they are no longer needed. To change the interval or disable heartbeat, see [Configuration: Heartbeat](./configuration.md#gateway-heartbeat).
