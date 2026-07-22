# Nanobot WebUI: Browser Workbench for Self-Hosted AI Agents

<!-- Meta description: Run nanobot from a browser WebUI with persistent chat sessions, visible tool activity, workspace controls, Apps, MCP presets, Skills, settings, and Automations. -->

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
WebSocket channel after confirmation, generates a WebUI bootstrap secret when
one is missing, starts the gateway, and opens the browser. The first-run path
binds the WebUI to `127.0.0.1` by default, so it is not available from other
devices on your LAN.

Run it in the background when you do not want to keep a terminal open:

```bash
nanobot webui --background
```

Manage the background gateway with `nanobot gateway status`, `nanobot gateway
logs`, `nanobot gateway restart`, and `nanobot gateway stop`.

Manual config still works. Same-machine localhost WebUI access can run without
a browser password. Set `tokenIssueSecret` when you intentionally expose the
WebUI beyond localhost or want a browser password:

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

## First 10 Minutes

Use the WebUI as the primary setup surface after Quick Start:

1. Send `Hello!` in a new chat to prove the selected model works.
2. Open **Settings → Models** and confirm the active model preset.
3. Start a separate chat before project work, then choose the intended workspace and access mode.
4. Add only one capability next: a chat channel in **Settings → Channels**, a web/voice/image provider in **Settings**, or an App/MCP integration in **Apps**.
5. Restart when the WebUI shows a restart requirement, then test that capability with the smallest possible request.

This path avoids hand-editing `config.json` for normal setup. Use the reference docs when you need an option the WebUI does not expose or when you manage config as code.

## What It Is For

| Area | Use it for |
|---|---|
| Chat | Start, switch, search, fork, and delete browser sessions |
| Agent activity | See thinking, tool calls, file edits with diffs, command output, and generated artifacts in context |
| Workspace | Pick the project workspace before asking for file or shell work |
| Access | Choose the access mode for local capabilities allowed by your gateway configuration |
| Composer | Send text, images, voice input, slash commands, and `@` mentions for Apps or MCP presets |
| Channels | Connect and validate chat platforms, install their optional support, and manage saved channel setup |
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

When the agent writes or edits files, the activity item shows the target path,
status, changed line counts, and, when available, a unified diff. Use **View
diff** to expand the change; large diffs may hide unchanged lines or truncate the
inline preview. Use **Open file** from a file edit to open the read-only file
preview panel.

File previews follow the active session access mode. Restricted workspace access
previews only files under the selected workspace. Full Access can preview files
outside the workspace when that access mode is allowed by the gateway.

## Workspace and Access

Use the workspace picker before starting project-specific work. This gives the
agent the right project context for file paths, shell commands, and session
metadata.

Selecting a project does not replace the configured agent workspace. The two
paths have different responsibilities:

| Selected project provides | Agent workspace continues to provide |
|---|---|
| Project `AGENTS.md` | `SOUL.md` and `USER.md` |
| Relative file paths and shell working directory | Long-term memory and history |
| The normal read/write boundary in Restricted mode | Custom skills and instance state |

Project-local `SOUL.md` and `USER.md` files are ignored, and the agent workspace's
`AGENTS.md` is not inherited by a separately selected project. When the selected
project is the configured agent workspace, both roles naturally use the same
directory.

The access control in the composer controls the local capability level for the
chat. It does not bypass your gateway, provider, shell sandbox, or operating
system configuration; it only selects among the capabilities that are already
available to this WebUI session.

In Restricted mode, ordinary file and shell work stays inside the selected
project. To preserve agent continuity, filesystem/search tools receive narrow,
read-only access to built-in skills, custom skills in the agent workspace, and
the exact agent `memory/history.jsonl` file. This does not grant access to
neighboring memory or profile files, and it does not allow writes outside the
selected project. These tool exceptions do not broaden the browser's file
preview boundary.

Remote WebUI sessions may reduce access for the current workspace. Selecting a
different workspace or enabling Full Access remains limited to local and native
clients.

## Composer

The composer supports plain messages, image attachments, voice input when
transcription is configured, slash commands, and `@` mentions for installed Apps
or MCP presets. The model badge shows the current model or preset and links back
to model settings when setup is incomplete.

For image generation, configure an image provider first and then use the WebUI
image mode from the composer. See [`image-generation.md`](./image-generation.md)
for provider setup and output behavior.

## Channels

Open **Settings → Channels** to connect chat apps without assembling JSON by hand. Search for a platform, open its setup panel, and follow the fields or QR flow shown for that channel. The guided setup can:

- install missing optional channel support when the WebUI is running locally;
- collect platform credentials while preserving previously saved values;
- handle supported QR-based login flows;
- validate the connection and show actionable setup errors;
- tell you when the gateway needs to restart.

The platform itself may still require you to create a bot, enable event permissions, copy a token, or configure a webhook. Use [`chat-apps.md`](./chat-apps.md) for those platform-side prerequisites and for manual JSON/reference options.

Test a new channel with a private DM. When a supported channel sends a pairing code, the WebUI surfaces the pending request so you can approve the sender. Keep access narrow; do not use a wildcard allowlist unless public access is intentional.

## Apps

Open Apps from the sidebar to manage tools that nanobot can attach to a chat
turn. The default **Ready** view shows only tools that can be used immediately:

- **Apps** are local command-line adapters that nanobot runs on your machine.
  Installing an adapter does not modify the native desktop or web app it
  connects to.
- **Integrations** are MCP servers. Presets provide known configurations, and
  the custom integration panel accepts stdio, HTTP, and SSE servers.

Apps intentionally does not list nanobot runtime support packages such as
`api` or `bedrock`. Those packages enable providers, servers, or channels; they
are not tools that can be attached to a turn with `@`. Manage them from
**System**, **Models**, or **Web**. PDF and common Office document readers are
included in nanobot and activate automatically when a file is attached. The
equivalent CLI for optional integrations remains `nanobot plugins`. See
[`cli-reference.md`](./cli-reference.md#optional-features).

Some MCP presets connect to hosted keyless endpoints. For example, the Firecrawl
preset uses Firecrawl's hosted MCP endpoint for search, scrape, crawl, and
extraction tools without requiring an API key. This does not replace nanobot's
built-in web search provider; mention the Firecrawl MCP preset with `@` when a
turn needs Firecrawl's richer web data tools.

The Parallel Search preset connects to the free, anonymous Parallel Search MCP
endpoint and exposes `web_search` and `web_fetch` without requiring an API key.
It is an optional integration and does not replace nanobot's built-in web search
provider; mention `@parallel-search` when a turn should use it.

After an App or integration is available, mention it from the composer with
`@` to attach that tool to the next message.

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

For the full automation model, creation flow, trigger CLI usage, and delivery
semantics, see [`automations.md`](./automations.md).

There are two user-facing automation types:

- Scheduled automations, created by the agent's cron tool, run at a time,
  interval, or cron expression.
- Local triggers, created with `/trigger <name>`, run when you call a local
  command such as `nanobot trigger trg_8K4P2Q9X "Review PR #4502"`.

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
runtime configuration. Use it to review or adjust model presets, providers,
image generation, voice transcription, web tools, chat channels, Apps,
Automations, Skills, runtime identity, and advanced safety controls.

Some settings take effect immediately. Runtime settings that affect the gateway
or agent process may require a restart; the WebUI shows that requirement next to
the relevant control.

Browser-only display preferences, such as file edit display mode, take effect
immediately for the current browser and do not change gateway configuration.

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

Remote WebUI clients with a valid token can view and use Apps. Actions that
install missing nanobot support packages, such as adding a channel dependency,
are blocked by default. To let trusted remote administrators change the Python
environment through the WebUI, opt in explicitly:

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
