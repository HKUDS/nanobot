# WebUI

The WebUI is nanobot's browser workbench for persistent chat sessions, visible
agent activity, workspace controls, Apps, Skills, settings, and Automations in
one place.

The published `nanobot-ai` wheel already includes the WebUI bundle. You only need
the `webui/` source directory when you are changing the frontend itself.

## Open the WebUI

Use the launcher:

```bash
nanobot webui
```

`nanobot webui` creates the config/workspace when needed, checks provider setup,
offers Quick Start when the model provider is not ready, enables the local
WebSocket channel after confirmation, starts the gateway, and opens the browser.
The first-run path binds the WebUI to `127.0.0.1` by default, so it is not
available from other devices on your LAN.

Run it in the background when you do not want to keep a terminal open:

```bash
nanobot webui --background
```

Manage the background gateway with `nanobot gateway status`, `nanobot gateway
logs`, `nanobot gateway restart`, and `nanobot gateway stop`.

Manual config still works. Set `tokenIssueSecret` when you intentionally expose
the WebUI beyond localhost or want a browser password:

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "127.0.0.1",
      "tokenIssueSecret": "your-webui-password",
      "websocketRequiresToken": true
    }
  }
}
```

The WebUI is served by the WebSocket channel on port `8765` by default. The
gateway health endpoint, `18790` by default, is not the browser UI.

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
| Automations | Review, search, run, pause, edit, and delete scheduled and local-trigger agent turns |
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
nanobot can call from a chat. Nanobot features can enable built-in channels and
optional capabilities such as `bedrock` or `documents`. CLI Apps install local
adapters that nanobot runs on your machine; they do not modify the native apps
themselves. MCP presets add predefined MCP server configurations.

Enabling a Nanobot feature may install Python packages into the environment
running nanobot. By default, the WebUI can install missing packages only when
you open it on the same machine as nanobot. If you open the WebUI from another
device, a domain name, a tunnel, or a reverse proxy, package install is blocked
unless you explicitly allow it with `tools.webuiAllowRemotePackageInstall`.

Optional feature installs use your existing pip download settings. If PyPI is
slow or unavailable from your network, configure pip or set `PIP_INDEX_URL`
before starting nanobot.

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

Automations are agent turns that run later in a linked chat/session. They should
be created from the chat, channel, or session where they are supposed to run so
nanobot keeps the correct target context. When an automation runs, it normally
delivers the result back to that linked chat.

There are two user-facing automation types:

- Scheduled automations, created by the agent's cron tool, run at a time,
  interval, or cron expression.
- Local triggers, created with `/trigger <name>`, run when you call a local
  command such as `nanobot trigger trg_8K4P2Q9X "Review PR #4502"`.

If a GitHub webhook, CI system, or another service should wake nanobot up, keep
that webhook/service outside nanobot and have it call the trigger command with
the final message.

Trigger deliveries use the same workspace as the gateway. They survive gateway
restarts and are requeued if the process exits before the linked turn completes.
If the linked session is already running a turn, the local trigger waits until
that session is idle instead of being injected into the active turn. This is an
at-least-once local queue, so repeated delivery is possible after an interrupted
process. A delivered trigger is recorded as an automation turn in the linked
session; if the agent receives it but the turn fails, Automations marks the run
failed instead of retrying indefinitely.

For recurring background checks that should stay quiet unless there is something
useful to report, use the protected heartbeat job by editing `HEARTBEAT.md`
instead of creating a chat automation.

Use the Automations view to:

- Filter by all, active, paused, needs-attention, or system jobs.
- Search by task name, message, trigger command, linked chat, schedule, or status.
- Sort by next run, last run, updated time, or name.
- Run scheduled automations now.
- Pause or resume, rename, or delete user-created automations.
- Copy the CLI command for local triggers.
- Inspect protected system automations without changing them.

Search accepts plain text and field filters such as `name:backup`,
`chat:WeChat`, `schedule:09:30`, `cron:"0 23 * * *"`, `trigger`, and
`status:paused`.

An automation without a linked chat cannot be enabled or run from the WebUI,
because nanobot would not know where to deliver the scheduled turn. Recreate it
from the target chat or channel so the automation has complete context.

Local triggers do not have a WebUI "Run now" action because each run needs a
message. Use the copied `nanobot trigger ...` command and replace `"message"`
with the content that should be delivered.

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

Remote WebUI clients can view Apps and toggle already-installed features with a
valid token, but they cannot install missing Python packages by default. To allow
trusted remote admins to install optional feature dependencies from the WebUI,
opt in explicitly:

```json
{
  "tools": {
    "webuiAllowRemotePackageInstall": true
  }
}
```

Use this only for a private deployment where every authenticated WebUI user is
trusted to change the Python environment that nanobot runs in. If you publish
the WebUI through Nginx, Caddy, Cloudflare Tunnel, or a similar service, treat it
as remote access and leave package installs disabled unless that is intentional.

Optional feature installs use pip's configured package index, including
`PIP_INDEX_URL`.

Leave remote package installs disabled when the WebUI is exposed beyond a
private, trusted network.

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
