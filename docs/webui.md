# Nanobot WebUI: Browser Workbench for Self-Hosted AI Agents

<!-- Meta description: Run nanobot from a browser WebUI with persistent and temporary chats, visible tool activity, workspace controls, Apps, skill discovery, settings, and Automations. -->

The WebUI is nanobot's browser workbench. It is included with `nanobot-ai` and shares the same gateway, settings, and saved conversations as the terminal UI (TUI).

For a visual tour, see the [README feature gallery](../README.md#-webui).

## Open the WebUI

```bash
nanobot webui
```

On a fresh install, nanobot creates your config and workspace, starts the local gateway, and opens a signed-in browser window at `http://127.0.0.1:8765` (accessible only from your computer). Before your first chat, add a provider and model in **Settings → Models** (see [Configure Your Model](./quick-start.md#2-configure-your-model)).

With the official installer, the gateway stays running in the background after you close the browser or terminal. Manage it with `nanobot gateway status`, `logs`, `restart`, and `stop`. For other install methods (such as `uv` or `pip`), use `nanobot webui --detach` or `nanobot gateway --background` to keep it running in the background.

To sign in from another browser on the same machine, copy the **complete login link** printed in the terminal (shaped like `http://127.0.0.1:8765/#...`, including everything after `#`)—the bare address without the `#...` token will not sign a new browser in. Keep that link private. Use `nanobot webui --no-open` to print the link without launching a browser.

<details>
<summary>Manual configuration for the local WebUI</summary>

Localhost access does not require a browser password by default. To require a password or allow access from other devices, set `tokenIssueSecret` in `~/.nanobot/config.json`:

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

</details>

### macOS Dock icon

On a local macOS desktop, `nanobot webui` adds a Dock shortcut to your running WebUI (`--no-dock` disables it). Quitting or hiding the Dock icon only hides the shortcut; it does not stop the gateway or running tasks.

## Overview

| Area | What you can do |
|---|---|
| Topics | Start persistent topics or temporary chats; search, reorder, rename, archive, fork, or delete topics |
| Conversation groups | Work in up to four topics side by side with resizable panes |
| Activity & context | Inspect reasoning, tool calls, file diffs, token/cache usage, and the file graph |
| Workspace & Access | Pick a project folder and choose **Restricted** or **Full Access** |
| Composer | Send text, images, files, videos, voice input, `!` shell commands, `/` commands, and `@` mentions |
| Channels | Connect Telegram, Discord, Slack, Feishu, WeChat, Linear, and more with guided setup |
| Apps | Manage Agent Plugins, CLI Apps, and MCP servers |
| Skills | Inspect installed skills or discover new ones from skills.sh and SkillHub |
| Automations | Review, run, pause, edit, and delete scheduled tasks and local triggers |
| Settings | Configure models, providers, capabilities, appearance, and updates |

## Topics and Panes

Each topic in the sidebar keeps its own history, title, project folder, and linked automations. Use **New topic** for a fresh context, or **Fork** to branch off an existing conversation without changing the original.

- **Organize:** Drag topics to reorder them, or use **Rename** to edit a title inline.
- **Bulk actions:** Choose **Select** in a topic's menu to archive or delete multiple topics at once (press `Esc` to exit selection mode). Archived topics disappear from the ordinary list in every connected window. To bring one back, choose **Show archived** and restore it from its menu. Archiving keeps the conversation history and does not stop running tasks.
- **Delete with undo:** Deleting a topic hides it with an 8-second **Undo** window. Topics with linked automations pause for confirmation in the toast before starting the undo countdown.
- **Navigate long conversations:** Use the message rail on wide screens or prompt-summary search in the header to jump directly to earlier messages. Scroll past the top (or pull down on touch devices) to load older history.

### Edit a sent message

In a saved topic, wait for the reply to finish, then open **Message actions** on one of your plain-text messages and choose **Edit message**. Edit the text directly in the bubble. Below it, **×** cancels without changing the conversation or your composer draft. **✓** resends: it replaces the selected message and everything after it in the same topic, then generates a new reply. It does not undo earlier tool actions such as file changes. To keep the original conversation, use **Fork** instead.

Messages with attachments, quotes, mentions, or commands cannot be edited this way.

### Conversation groups and panes

Open a topic's menu and choose **Create group** to arrange up to four topics side by side. Use **Add pane** in the header to start another topic alongside it, or drag an existing topic into the group.

Selecting a pane targets the composer at that topic. Grouping only arranges panes—it does not merge topic histories. To pull context from another topic, mention it with `@`.

### Model options for a topic

Open the model preset menu beside the composer to adjust **Reasoning effort** (and **Fast** / **Ultrafast** speed boosts on supported Codex models) for the current topic without changing the shared preset. Switching presets resets these per-topic overrides.

## Composer

The composer supports text, images, documents, videos, voice input, slash commands, and `@` mentions.

- **Sending:** On desktop, `Enter` sends and `Shift+Enter` adds a newline. On touch devices, `Enter` adds a newline and the send button submits.
- **Queuing while busy:** While nanobot is replying on desktop, pressing `Enter` adds to a waiting message that sends automatically when the reply finishes. Use **Send now** (or press `Enter` on an empty box) to send it immediately as guidance—a dashed border shows when a follow-up is waiting for the model, returning to normal once the model picks it up.
- **Attachments:** Drop or select images, PDFs, Office documents, or videos (MP4/WebM/MOV, one per message up to 20 MiB; videos play in the WebUI, though the agent cannot analyze video contents yet).
- **Attach host files by path:** Paste a file path on the nanobot host on its own line to reference it without uploading or copying (respects the topic's workspace permissions).
- **Direct shell commands:** Start a message with `!` (such as `!git status`) to run a command directly in the topic's workspace without calling the model.
- **Mention other topics:** Type `@` (or drag a topic from the sidebar) to reference up to eight topics in one message—for example, *"Summarize @luma"* or *"Send this update to @luma."*
- **Voice input:** When voice transcription is enabled in Settings, the empty composer shows a microphone button.
- **Image generation:** Enable image generation in Settings to create and edit images in chat (see [Image Generation](./image-generation.md)).

## Workspace and Access

Click the workspace picker when starting a new topic to browse folders on the nanobot host, jump to recent or starred projects, or enter a path directly (`Cmd/Ctrl+Shift+G`). Changes apply when you click **Confirm**. Saved topics keep their project folder fixed; start a new topic to work in a different project.

Selecting a project folder sets the working directory for files and shell commands without changing your agent's identity or memory:

| Selected project provides | Agent workspace continues to provide |
|---|---|
| Project `AGENTS.md` | `SOUL.md` and `USER.md` |
| Relative file paths and shell working directory | Long-term memory (`memory/`) |
| The read/write boundary in **Restricted** mode | Custom skills (`skills/`) and instance state |

> [!NOTE]
> Starting a new topic or selecting a different project does not create separate long-term memory. If you need strict separation between clients or users, use [Multiple Instances](./multiple-instances.md).

Use the access control in the composer to choose between **Restricted** (file and shell work stays inside the selected project, with narrow read-only access to skills and agent memory wiki) and **Full Access** (when allowed by your gateway config). You can switch access mode while a topic is idle.

## Activity, Previews, and Subtasks

### Activity and context usage

While nanobot works, **Working for** shows its live step and timer; click it to view full reasoning and tool calls (or set **Settings → Appearance → Activity details** to **Expanded**). After a turn finishes, expand **Worked for** to inspect the full trace.

Tasks in persistent topics keep running even if your browser disconnects; status and completed replies sync when you reconnect.

Click the context indicator beside the model badge to inspect:

- **Context usage & recent rounds:** Estimated token usage, generation time, and cache hits (estimates only, not a billing statement).
- **File graph:** Files read since the last compaction and local Markdown links between them. Click any node to inspect its estimated size or preview the file, and scrub the usage bar to replay earlier rounds.

When a conversation grows long, nanobot summarizes earlier turns while keeping your full chat history visible. You can also run `/compact` anytime (see [Memory](./memory.md)).

### File and diagram previews

In a streaming reply, a Mermaid block shows source until its closing fence arrives. The visible diagram then renders while the rest of the reply continues. If the renderer fails to load, a retry icon appears next to Copy. Hover over it or focus it to read the error, or click it to render the diagram again without refreshing the chat.

File edits show the path and changed line counts. Change **Settings → Appearance → File edit display** between **Summary**, inline **Diff**, and **Collapsed diff**. Click any filename to open a read-only preview tab (text previews up to 384 KiB; PNG/JPEG/GIF/WebP images up to 8 MiB; Markdown renders with a **Source** toggle; Mermaid diagrams render automatically). Right-click a file reference or tab to copy its path.

### Model failures

If a model call fails after automatic retries stop, any partial reply is preserved and the WebUI shows why it failed. Click **Continue** to resume from the saved conversation, or open model settings to fix credentials or switch models. Review completed tool calls before continuing, as the model may re-run tools if needed.

### Delegated work

When nanobot delegates work to subagents, a **Subtasks** bar appears above the composer while tasks are active. Open it to watch live progress, inspect a subtask's read-only trace, or stop an individual subtask. Finished subtasks appear inline beside the message that started them. See [Subagents](./concepts.md#subagents) for cancellation and restart behavior.

## Temporary Chats

Choose **New topic → Temporary chat** when you want a throwaway conversation that does not use your agent profile or long-term memory and is never saved to history.

- You can keep multiple temporary chats open in the sidebar during one browser session.
- Reloading the page, closing the tab, losing the connection, or restarting the gateway permanently deletes all temporary chats.
- Temporary chats always run in the default workspace in **Restricted** mode and cannot create goals, automations, or subagents.

> [!WARNING]
> Temporary does not mean consequence-free. Prompts still go to your AI provider, and tools can still edit files, run commands, or call external services. Files created by tools are not automatically deleted when the chat closes.

## Channels

Open **Channels** to connect Telegram, Discord, Slack, Feishu, WeChat, Linear, and other platforms with credential forms or QR codes. On a local WebUI, nanobot can install missing channel packages for you and prompt to restart if needed.

Test each new channel with a direct message—if the channel replies with a pairing code, approve it right inside the WebUI. For platform-side setup steps (creating bots, tokens, or permissions), see [Chat Apps](./chat-apps.md).

## Apps

Open **Apps → Ready** and filter by **Agent Plugins**, **CLI Apps**, or **MCP**:

- **Agent Plugins:** Local packages under `<workspace>/plugins/` that bundle skills, MCP servers, or both. Enable them in **Apps** to activate them.
- **CLI Apps:** Local command-line tool adapters on the nanobot host (run in a limited environment without your provider API keys).
- **MCP:** Add stdio, HTTP, or SSE Model Context Protocol servers, or pick from built-in presets (including OAuth presets like Notion, Linear, and Xmind, and keyless search presets like Firecrawl and Parallel Search).

Once enabled, mention a CLI App or MCP server with `@` in the composer to use it in your next message, or invoke plugin skills with `$skill-name`.

## Skills

- **Skills → Installed:** Search, inspect, enable/disable, or delete built-in and workspace skills.
- **Skills → Discover:** Browse and install skills from **skills.sh** (requires Node.js / `npx`) and **SkillHub** (no `npx` needed).

> [!CAUTION]
> Marketplace skills are third-party instructions and may include scripts. Review them before installing, and only enable skills you trust with your workspace and tools.

## Automations

The **Automations** view lets you search, filter, run, pause, edit, and delete scheduled tasks and local triggers. Search supports plain text and filters like `name:backup`, `chat:WeChat`, `schedule:09:30`, `trigger`, and `status:paused`.

Create automations from the topic where you want replies delivered. Local triggers need a message each time they run, so copy their `nanobot trigger ...` command instead of using "Run now". See [Automations](./automations.md) for the complete guide.

## Settings and Updates

Settings that require a gateway restart are clearly marked in the WebUI.

- **Appearance:** Choose **System**, **Light**, or **Dark** theme, pick a reading text size (Small, Standard, Large, or custom 14–28 px), choose how much activity/diff detail to show, or set a custom background image (**Settings → Appearance → Background**—PNG, JPEG, or WebP up to 6 MiB, with adjustable blur and fade).
- **Notifications:** Open **Settings → Notifications** to turn on **Browser notifications** (alerts you when a background task finishes or needs attention; click **Test notification** to verify) and **Completion sound**. Works on localhost or HTTPS (on iPhone/iPad, open from the Home Screen).
- **Check for updates:** Open **Settings → About** to check for updates. nanobot does not run automatic background version checks or auto-install updates without your confirmation. See [Updating nanobot](./updating.md).

## Sharing Access

The WebUI is an admin workbench for one nanobot instance. Everyone signed in to the WebUI shares all topics and administrative controls—there are no per-user accounts or private topics.

- Only share WebUI access with people you trust to administer the same agent.
- To let others chat without admin access, connect a [chat app](./chat-apps.md) and approve them via pairing or allowlists.
- To isolate memory and data between different users or clients, run [separate instances](./multiple-instances.md).

## LAN Access

To access the WebUI from another device on your local network, bind it to `0.0.0.0` and set a password (`tokenIssueSecret`):

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

The gateway refuses to bind to `0.0.0.0` without `token` or `tokenIssueSecret`. After restarting, open `http://<your-ip>:8765` on the other device and sign in with your secret.

- **Voice input on LAN:** Browsers require HTTPS for microphone access on non-localhost addresses. Configure [TLS/SSL](./websocket.md#tlsssl) or put an HTTPS reverse proxy in front of the WebUI.
- **Remote installs:** By default, remote browsers cannot install optional packages or marketplace skills. Only enable `tools.webuiAllowRemotePackageInstall: true` on private deployments where every WebUI user is trusted to install packages and scripts on the host.

## Troubleshooting

If the WebUI will not open, check these in order:

1. `nanobot agent -m "Hello!"` works in the same Python environment.
2. `channels.websocket.enabled` is not set to `false` in `~/.nanobot/config.json`.
3. `nanobot gateway` is running.
4. You are opening port `8765` (WebUI), not `18790` (gateway health check).
5. For LAN access, `host` is `"0.0.0.0"` and `tokenIssueSecret` (or `token`) is set.

For more help, see [WebUI Problems](./troubleshooting.md#webui-problems).
