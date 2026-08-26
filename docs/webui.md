# Nanobot WebUI: Browser Workbench for Self-Hosted AI Agents

<!-- Meta description: Run nanobot from a browser WebUI with persistent and temporary chats, visible tool activity, workspace controls, Apps, skill discovery, settings, and Automations. -->

The WebUI is nanobot's browser workbench for persistent topics, temporary
chats, visible agent activity, workspace controls, Apps, skill discovery,
settings, and Automations in one place.

The published `nanobot-ai` wheel already includes the WebUI bundle. You only need
the `webui/` source directory when you are changing the frontend itself.

## Open the WebUI

Use the launcher:

```bash
nanobot webui
```

`nanobot webui` creates the config/workspace when needed, enables the local
WebSocket channel after confirmation, generates a WebUI bootstrap secret when
one is missing, starts or joins the same on-demand gateway used by the native
TUI, and opens the browser. With a fresh config,
it can open before a model is configured so you can finish setup in **Settings
→ Models**. The first-run path binds the WebUI to `127.0.0.1` by default, so
it is not available from other devices on your LAN.

After model setup, explicitly promote the shared gateway when you do not want to keep a client open:

```bash
nanobot gateway --background
```

`nanobot webui --background` is retained only to print migration guidance. This keeps one
unambiguous owner for persistent process lifecycle.

Each foreground WebUI or TUI launcher releases only its own client. The last
interactive launcher stops an on-demand gateway. `nanobot gateway --background` makes the
gateway persistent; manage it with `nanobot gateway status`, `nanobot gateway
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

Use the WebUI as the primary setup surface:

1. Open **Settings → Models** and configure a provider, credential, and active model preset.
2. Send `Hello!` in a new topic to prove the selected model works.
3. Start a separate topic before project work, then choose the intended workspace and access mode.
4. Add only one capability next: a chat channel in **Settings → Channels**, a web/voice/image provider in **Settings**, or an App/MCP integration in **Apps**.
5. Restart when the WebUI shows a restart requirement, then test that capability with the smallest possible request.

This path avoids hand-editing `config.json` for normal setup. Use the reference docs when you need an option the WebUI does not expose or when you manage config as code.

## What It Is For

| Area | Use it for |
|---|---|
| Topics | Start persistent topics or temporary chats; switch, search, reorder, fork, or delete persistent topics |
| Agent activity | See thinking, tool calls, file edits with diffs, command output, and generated artifacts in context |
| Workspace | Pick the project workspace before asking for file or shell work |
| Access | Choose the access mode for local capabilities allowed by your gateway configuration |
| Composer | Send text, images, voice input, slash commands, and `@` mentions for topics, Apps, or MCP presets |
| Channels | Connect and validate chat platforms, install their optional support, and manage saved channel setup |
| Apps | Install, test, update, and use local CLI App adapters and MCP presets |
| Skills | Inspect and manage installed skills, or discover skills from supported marketplaces |
| Automations | Review, search, run, pause, edit, and delete scheduled and local-trigger agent turns |
| Settings | Adjust models, providers, image generation, voice, web tools, runtime, and safety options |

## Topic Workspace

The sidebar is the topic switcher. Each topic keeps its own history, title,
workspace selection, and linked automations. Use a new topic when you want a
separate context; use fork when you want to continue from an existing point
without changing the original thread.

Drag a topic within its current sidebar group to keep frequently used work in
your preferred order. Drag a topic from the sidebar into the composer when you
want to reference it in the next message instead of switching to it.

The message timeline shows both user-visible replies and agent activity. Long
tool or reasoning sections can be expanded when you need the details.

When the agent writes or edits files, the activity item shows the target path,
status, changed line counts, and, when available, a unified diff. Use **View
diff** to expand the change; large diffs may hide unchanged lines or truncate the
inline preview. Use **Open file** from a file edit to open the read-only file
preview panel.

File previews follow the active topic's access mode. Restricted workspace access
previews only files under the selected workspace. Full Access can preview files
outside the workspace when that access mode is allowed by the gateway.

## Temporary Chats

Use a temporary chat for a conversation that should not be added to nanobot's
topic history or long-term memory:

1. Select **New topic**.
2. Select the **Temporary chat** control in the page header.
3. Send the first message.

You can keep more than one temporary chat open and switch between them under
**Temporary chats** in the sidebar while the current WebUI connection remains
open. Reloading or closing the page, restarting the gateway, or losing the
WebSocket connection ends all of them. They cannot be recovered afterward.

Temporary does not mean consequence-free. Requests still go to the configured
model provider, and tools can still change files, run commands, or affect
external services. Temporary chats always use the default workspace in
Restricted mode; the project picker and Full Access are unavailable. Commands
and tools that create durable goals, automations, or subagent work are also
unavailable. Use a regular topic when you need reusable context, scheduled work,
or a result you must retain.

## Workspace and Access

Use the workspace picker before starting project-specific work. This gives the
agent the right project context for file paths, shell commands, and topic
metadata. A locally hosted WebUI opens the operating system's folder chooser
when one is available; remote deployments keep the manual absolute path entry.

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
available to the current topic.

In Restricted mode, ordinary file and shell work stays inside the selected
project. To preserve agent continuity, filesystem/search tools receive narrow,
read-only access to built-in skills, custom skills in the agent workspace, and
the exact agent `memory/history.jsonl` file. This does not grant access to
neighboring memory or profile files, and it does not allow writes outside the
selected project. These tool exceptions do not broaden the browser's file
preview boundary.

Remote WebUI connections may reduce access for the current workspace. Selecting a
different workspace or enabling Full Access remains limited to local and native
clients.

## Composer

The composer supports plain messages, image attachments, voice input when
transcription is configured, slash commands, and `@` mentions for installed Apps,
MCP presets, or persisted topics. Topics have short, pronounceable handles such as
`@luma`; titles are display text rather than addresses. Select a topic
from the menu, or drag it from the sidebar, to attach its structured reference.
Typing the same text without selecting it remains plain text.

The agent can inspect an attached topic with `read_session`. It can discover other
persisted topics with `list_sessions` and send asynchronous messages with
`send_session_message`; topic messaging is not limited by workspace scope.
The model badge shows the current model or preset and links to model settings when
setup is incomplete.

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

Open Apps from the sidebar to review and manage installable capabilities. The
default **Ready** view shows only capabilities that can be used immediately:

- **Agent Plugins** are local packages that can bundle skills, MCP servers, or
  both. A package under `<workspace>/plugins/` is installed but remains inactive
  until you enable it in Apps.
- **CLI Apps** are local command-line adapters that nanobot runs on your
  machine. Their installer manages the executable and exposes its adapter
  through the same plugin activation model. Installing an adapter does not
  modify the native desktop or web app it connects to.
- **MCP** lists Model Context Protocol servers. Presets provide known
  configurations, and the **Add MCP server** panel accepts stdio, HTTP, and SSE
  servers. Custom HTTP/SSE servers can use no authentication, OAuth, or request
  headers. After saving an OAuth server, choose **Connect** to open its sign-in
  page. Presets such as Xmind, Notion, and Linear already use OAuth. HTTPS and
  localhost WebUIs return automatically; a remote plain-HTTP WebUI shows one
  field for pasting the complete localhost callback URL.

Apps intentionally does not list nanobot runtime support packages such as
`api` or `bedrock`. Those packages enable providers, servers, or channels; they
are not tools that can be attached to a turn with `@`. Manage them from
**System**, **Models**, or **Web**. PDF and common Office document readers are
included in nanobot and activate automatically when a file is attached. The
equivalent CLI for optional integrations remains `nanobot plugins`. See
[`cli-reference.md`](./cli-reference.md#optional-features).
That command manages nanobot runtime extras, not Agent Plugin packages.

Some MCP presets connect to hosted keyless endpoints. For example, the Firecrawl
preset uses Firecrawl's hosted MCP endpoint for search, scrape, crawl, and
extraction tools without requiring an API key. This does not replace nanobot's
built-in web search provider; mention the Firecrawl MCP preset with `@` when a
turn needs Firecrawl's richer web data tools.

The Parallel Search preset connects to the free, anonymous Parallel Search MCP
endpoint and exposes `web_search` and `web_fetch` without requiring an API key.
It is an optional integration and does not replace nanobot's built-in web search
provider; mention `@parallel-search` when a turn should use it.

After a CLI App or MCP server is available, mention it from the composer with
`@` to attach that tool to the next message. Plugin-provided skills participate
in normal skill discovery and can be invoked with `$skill-name`.

## Skills

Open **Skills → Installed** to review built-in and workspace-provided skills.
You can search and filter them, inspect their instructions and setup
requirements, enable or disable them, and delete workspace skills you no longer
want.

Open **Skills → Discover** to browse or search skills from skills.sh and
SkillHub. A marketplace skill is copied into the active agent workspace after
you confirm the installation. skills.sh installation requires Node.js with
`npx`; SkillHub installation does not.

Marketplace skills are third-party instructions and may include executable
scripts. Review the source and instructions before installing one, and enable
only skills you trust with the same files, tools, and credentials available to
your agent.

## Automations

Automations are agent turns that run later in a linked topic. Create them from
the topic or channel where they are supposed to run so nanobot keeps the
correct target context. When an automation runs, it normally delivers the
result back to that topic.

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
- Search by task name, message, trigger command, linked topic, schedule, or status.
- Sort by next run, last run, updated time, or name.
- Run scheduled automations now.
- Pause or resume, rename, or delete user-created automations.
- Copy the CLI command for local triggers.
- Inspect protected system automations without changing them.

Search accepts plain text and field filters such as `name:backup`,
`chat:WeChat`, `schedule:09:30`, `cron:"0 23 * * *"`, `trigger`, and
`status:paused`.

An automation without a linked topic cannot be enabled or run from the WebUI,
because nanobot would not know where to deliver the scheduled turn. Recreate it
from the target topic or channel so the automation has complete context.

Local triggers do not have a WebUI "Run now" action because each run needs a
message. Use the copied `nanobot trigger ...` command and replace `"message"`
with the content that should be delivered.

## Settings

Settings is the control surface for browser-local and gateway-backed
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

Plain HTTP is enough for basic WebUI access, but browsers expose microphone
capture only in secure contexts. Voice input works on same-machine localhost;
from another device, serve the WebUI over HTTPS with a certificate that device
trusts. Configure [`sslCertfile` and `sslKeyfile`](./websocket.md#tlsssl) on the
WebSocket channel and open `https://<your-host>:8765`, or terminate HTTPS at a
reverse proxy and use that proxy's HTTPS URL.

Remote WebUI clients with a valid token can view and use Apps and installed
skills. Actions that install missing nanobot support packages or third-party
marketplace skills are blocked by default. To let trusted remote administrators
perform those installations through the WebUI, opt in explicitly:

```json
{
  "tools": {
    "webuiAllowRemotePackageInstall": true
  }
}
```

Use this only for a private deployment where every authenticated WebUI user is
trusted to change nanobot's Python environment and install workspace skill
instructions or scripts. If you publish the WebUI through Nginx, Caddy,
Cloudflare Tunnel, or a similar service, treat it as remote access and leave
package and skill installs disabled unless that is intentional.

Optional feature installs use pip's configured package index, including
`PIP_INDEX_URL`. skills.sh marketplace installs use `npx` instead.

Leave remote package installs disabled when the WebUI is exposed beyond a
private, trusted network.

## Troubleshooting

If the page does not open, check these in order:

1. `nanobot agent -m "Hello!"` works in the same Python environment.
2. `~/.nanobot/config.json` does not explicitly set `channels.websocket.enabled` to `false`.
3. `nanobot gateway` is still running.
4. You are opening port `8765`, not the gateway health port.
5. LAN access uses `host: "0.0.0.0"` and a token or token issue secret.

If voice input asks for a secure connection, use HTTPS with a certificate the
device trusts. Browsers do not expose microphone capture to
`http://<your-ip>` origins.

For detailed diagnostics, see
[`troubleshooting.md#webui-problems`](./troubleshooting.md#webui-problems).
For frontend development, see [`../webui/README.md`](../webui/README.md).
