# WebUI

The WebUI is nanobot's browser workbench. Use it after a basic CLI reply already
works, when you want a persistent chat workspace, visible agent activity,
workspace controls, Apps, Skills, settings, and Automations in one place.

The published `nanobot-ai` wheel already includes the WebUI bundle. You only need
the `webui/` source directory when you are changing the frontend itself.

## Open the WebUI

First confirm your provider and model can answer:

```bash
nanobot agent -m "Hello!"
```

The local WebSocket channel is enabled by default because it serves the bundled
WebUI. To require a browser login password, merge `tokenIssueSecret` into your
existing `~/.nanobot/config.json`:

```json
{
  "channels": {
    "websocket": {
      "tokenIssueSecret": "your-webui-password",
      "websocketRequiresToken": true
    }
  }
}
```

If you are new to JSON snippets, see
[`start-without-technical-background.md#how-to-merge-json-snippets`](./start-without-technical-background.md#how-to-merge-json-snippets).

Start the gateway:

```bash
nanobot gateway
```

Leave the gateway running and open
[`http://127.0.0.1:8765`](http://127.0.0.1:8765). The WebUI is served by the
WebSocket channel on port `8765` by default. The gateway health endpoint,
`18790` by default, is not the browser UI.
Enter `tokenIssueSecret` when the WebUI asks for a password.

## What It Is For

| Area | Use it for |
|---|---|
| Chat | Start, switch, search, fork, and delete browser sessions |
| Agent activity | See thinking, tool calls, file activity, command output, and generated artifacts in context |
| Workspace | Pick the project workspace before asking for file or shell work |
| Access | Choose the access mode for local capabilities allowed by your gateway configuration |
| Composer | Send text, images, voice input, slash commands, and `@` mentions for Apps or MCP presets |
| Apps | Install, test, update, and use local CLI App adapters and MCP presets |
| Skills | Inspect available built-in and workspace skills before relying on them |
| Automations | Review, search, run, pause, edit, and delete scheduled agent turns |
| Settings | Adjust models, providers, image generation, voice, web tools, runtime, and safety options |

## Chat Workspace

The sidebar is the session switcher. A session keeps its own history, title,
workspace metadata, and linked automations. Use a new session when you want a
separate context; use fork when you want to continue from an existing point
without changing the original thread.

The message timeline shows both user-visible replies and agent activity. Long
tool or reasoning sections can be expanded when you need the details.

## Workspace and Access

Use the workspace picker before starting project-specific work. This gives the
agent the right project context for file paths, shell commands, and session
metadata.

The access control in the composer controls the local capability level for the
chat. It does not bypass your gateway, provider, shell sandbox, or operating
system configuration; it only selects among the capabilities that are already
available to this WebUI session.

## Composer

The composer supports plain messages, image attachments, voice input when
transcription is configured, slash commands, and `@` mentions for installed Apps
or MCP presets. The model badge shows the current model or preset and links back
to model settings when setup is incomplete.

For image generation, configure an image provider first and then use the WebUI
image mode from the composer. See [`image-generation.md`](./image-generation.md)
for provider setup and output behavior.

## Apps

Open Apps from the sidebar or settings navigation to manage integrations that
nanobot can call from a chat. CLI Apps install local adapters that nanobot runs
on your machine; they do not modify the native apps themselves. MCP presets add
predefined MCP server configurations.

Some MCP presets connect to hosted keyless endpoints. For example, the Firecrawl
preset uses Firecrawl's hosted MCP endpoint for search, scrape, crawl, and
extraction tools without requiring an API key. This does not replace nanobot's
built-in web search provider; mention the Firecrawl MCP preset with `@` when a
turn needs Firecrawl's richer web data tools.

After an App or MCP preset is available, mention it from the composer with `@`
to attach that capability to the next message.

## Skills

The Skills view shows the skill instructions available to the agent, including
built-in skills and workspace-provided skills. Check this view when you want to
know whether nanobot already has a focused workflow for a task before you ask it
to perform that task.

## Automations

Automations are scheduled agent turns. They should be created from the chat,
channel, or session where they are supposed to run so nanobot keeps the correct
target context.

Use the Automations view to:

- Filter by all, active, paused, needs-attention, or system jobs.
- Search by task name, message, linked chat, schedule, or status.
- Sort by next run, last run, updated time, or name.
- Run now, pause or resume, edit, or delete user-created automations.
- Inspect protected system automations without changing them.

Search accepts plain text and field filters such as `name:backup`,
`chat:WeChat`, `schedule:09:30`, `cron:"0 23 * * *"`, and `status:paused`.

An automation without a linked chat cannot be enabled or run from the WebUI,
because nanobot would not know where to deliver the scheduled turn. Recreate it
from the target chat or channel so the automation has complete context.

## Settings

Settings is the control surface for the browser session and gateway-backed
runtime configuration. Use it to review or adjust model presets, provider
visibility, image generation, voice transcription, web tools, Apps, Automations,
Skills, runtime identity, and advanced safety controls.

Some settings take effect immediately. Runtime settings that affect the gateway
or agent process may require a restart; the WebUI shows that requirement next to
the relevant control.

## LAN Access

To open the WebUI from another device on the same network, bind the WebSocket
channel to all interfaces and set a token or token issue secret:

```json
{
  "channels": {
    "websocket": {
      "host": "0.0.0.0",
      "port": 8765,
      "tokenIssueSecret": "your-secret-here"
    }
  }
}
```

The gateway refuses to start with `host` set to `"0.0.0.0"` unless `token` or
`tokenIssueSecret` is configured. After the gateway starts, open
`http://<your-ip>:8765` from the other device and enter the secret in the login
form.

## Troubleshooting

If the page does not open, check these in order:

1. `nanobot agent -m "Hello!"` works in the same Python environment.
2. `~/.nanobot/config.json` does not explicitly set `channels.websocket.enabled` to `false`.
3. `nanobot gateway` is still running.
4. You are opening port `8765`, not the gateway health port.
5. LAN access uses `host: "0.0.0.0"` and a token or token issue secret.

For detailed diagnostics, see
[`troubleshooting.md#webui-problems`](./troubleshooting.md#webui-problems).
For frontend development, see [`../webui/README.md`](../webui/README.md).
