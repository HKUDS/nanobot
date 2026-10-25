# Nanobot WebUI: Browser Workbench for Self-Hosted AI Agents

<!-- Meta description: Run nanobot from a browser WebUI with persistent and temporary chats, visible tool activity, workspace controls, Apps, skill discovery, settings, and Automations. -->

The WebUI shares its gateway and saved sessions with the native terminal client and is included with `nanobot-ai`.

For a visual tour, see the [README feature gallery](../README.md#-webui). This guide follows the current source tree; some features are newer than the published release.

## Open the WebUI

```bash
nanobot webui
```

On a new installation, the launcher asks for confirmation to create the config and workspace, enables the local WebUI, and opens a signed-in browser. Configure a provider and model in **Settings → Models** before sending your first message; see [Configure Your Model](./quick-start.md#2-configure-your-model). The default address is `http://127.0.0.1:8765`, accessible only from the same machine.

Official-installer environments start a persistent gateway by default. Other installations keep it attached to the launchers: closing the last WebUI or TUI launcher stops an on-demand gateway. Use `nanobot webui --detach` to keep it running after the terminal closes, or start it explicitly:

```bash
nanobot gateway --background
```

Manage a persistent gateway with `nanobot gateway status`, `nanobot gateway logs`, `nanobot gateway restart`, and `nanobot gateway stop`. Use the printed instance-specific commands for a custom config or workspace. The old `nanobot webui --background` flag is deprecated; `--detach` cannot be combined with `--dev`.

To sign in another browser, use the complete printed login link, including the fragment after `#`. Treat it as a credential. `nanobot webui --no-open` prints the link without opening a browser. In WSL, the launcher uses the Windows default browser unless `BROWSER` is set; if automatic opening fails, use the printed link.

The launcher displays gateway warnings and errors; use the printed logs command for full output.

<details>
<summary>Manual configuration for the local WebUI</summary>

Listener and authentication fields are configured in `config.json`. Localhost access can run without a browser password; set `tokenIssueSecret` for access beyond localhost or to require a password:

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

On a local macOS desktop, `nanobot webui` provides a Dock shortcut to the running WebUI. `--no-open` keeps the shortcut without opening a page; `--no-dock` disables it. It is unavailable in SSH/headless sessions or for non-loopback browser addresses.

Attached launchers share the shortcut until the last matching WebUI launcher exits. With `--detach` or official-installer background launch, it remains until the gateway stops and returns after restart or update. It is a shortcut to a running instance, not a standalone app.

**Hide Dock Icon** or quitting the icon hides the shortcut without stopping the gateway or its tasks, until the next explicit launch or service restart. In detached mode, `--no-dock` also disables it for later restarts; launching without that flag enables it again.

## Navigate a long conversation

The message rail on wide screens and prompt-summary search in the header jump to saved prompts, loading the surrounding messages as needed. Loading errors leave the current content available for retry. Older compatible hosts may only support navigation among already-loaded messages.

## Sharing access

The WebUI administers one nanobot instance. Signed-in users share saved topics and administrative controls; there are no per-user roles or private topic ownership boundaries. The [remote installation restriction](#lan-access) limits package installation, not other administrative access.

Share WebUI access only with people you trust to administer the same agent. To give someone chat access without the administration interface, connect a [chat platform](./chat-apps.md) and configure its access policy. Channel approval still does not create a separate agent or memory store. For separate clients or users whose data must not mix, use [separate instances](./multiple-instances.md).

## What It Is For

| Area | Use it for |
|---|---|
| Topics | Start persistent topics or temporary chats; switch, search, reorder, fork, or delete persistent topics |
| Conversation groups | Arrange up to four independent topics in one workbench with resizable panes |
| Agent activity | See thinking, tool calls, file edits with diffs, command output, and generated artifacts in context |
| Context usage | Inspect current context size, per-round token and cache usage, and compaction progress |
| Workspace | Pick the project workspace before asking for file or shell work |
| Access | Choose the access mode for local capabilities allowed by your gateway configuration |
| Composer | Send text, images, voice input, slash commands, and `@` mentions for topics, Apps, or MCP presets |
| Channels | Connect and validate chat platforms, install their optional support, and manage saved channel setup |
| Apps | Install, test, update, and use local CLI App adapters and MCP presets |
| Skills | Inspect and manage installed skills, or discover skills from supported marketplaces |
| Automations | Review, search, run, pause, edit, and delete scheduled and local-trigger agent turns |
| Settings | Adjust models, providers, image generation, voice, web tools, runtime, and safety options |

## Check for updates

Open **Settings → About** to check for updates automatically. Startup, reconnecting, and normal chatting do not trigger background version checks. Use **Check again** or **Retry** to check manually; changing the update channel also refreshes its status. Checking does not install updates or restart nanobot.

## Topic Workspace

The sidebar is the topic switcher. Each topic keeps its own history, title, workspace selection, and linked automations. Use a new topic when you want a separate context; use fork when you want to continue from an existing point without changing the original thread.

Drag topics within a sidebar group to reorder them. **Rename** edits a topic title in place; a failed save keeps the draft for retry.

### Conversation groups and panes

Open a topic's sidebar action menu and choose **Create group** to turn it into a conversation group. Use **Add pane** in the workbench header to start another topic alongside it. A group holds up to four panes. To bring in an existing topic, drag it onto the group or use **Move to** in its action menu.

**Pane layout** controls the arrangement of resizable panes. Selecting a pane directs the shared composer to that topic. Group membership and layout persist across refreshes; grouping does not merge topic histories.

To use work from another topic, mention it with `@` and tell nanobot what you need. See [Composer](#composer) for how to add a topic reference.

### Activity and context usage

The message timeline shows replies and agent activity. Expand the **Worked for** section to inspect the reasoning and tool activity for a completed turn.

Scroll past the oldest loaded message, or pull down and release on touch devices, to load earlier history. A red indicator offers error details and retry; **No earlier messages** marks the history boundary.

Tasks in persistent topics can continue while the connection is lost. Status and completed replies update after reconnecting; some missed text may appear only when the task finishes. [Temporary chats](#temporary-chats) end on connection loss.

The context indicator beside the model badge shows context-window usage. **Recent rounds** includes token usage, generation time and KV cache hits when reported. Provider figures may be estimated or unavailable and are not a billing statement.

During compaction, the model switches to a summary plus subsequent messages; the original messages remain in chat history. Use `/compact` to compact the current topic manually. See [Memory](./memory.md) for compaction and Dream consolidation.

### File and diagram previews

File activity shows the path, status and changed line counts. **Settings → Appearance → File edit display** offers **Summary**, inline **Diff**, or **Collapsed diff** with **View diff**. Large patches may omit unchanged lines or be truncated. Select a filename to open its read-only preview.

Files share a tabbed preview pane. Tabs and pane width are remembered per topic until the session is deleted or the WebUI connection ends.

Selecting a Markdown file opens **Preview**; **Source** shows the original text. Relative file links resolve from the document's folder and follow the same access checks. Images are not loaded automatically, section-only links remain text, and HTML/MDX components do not execute.

Text previews are limited to 384 KiB and indicate truncation. Very large or minified source may remain plain text. Image previews support PNG, JPEG, GIF and WebP up to 8 MiB. HTML and SVG files display as read-only source.

Explicit Markdown images appear inline; image attachments use a gallery. Other files appear as compact download cards below the image and video previews, with a file-type icon, filename and download action. File-type icons do not indicate preview support. Ordinary image file links open the preview instead.

Mermaid diagrams render after the reply finishes. The source remains available if rendering fails. Links, external images and executable HTML inside diagrams are disabled.

Right-click a file reference or preview tab to copy its absolute or project-relative path on the connected host. Files outside the project have no project-relative path; unresolved references can only be copied as written.

File previews follow the active topic's access mode. Restricted workspace access previews only files under the selected workspace. Full Access can preview files outside the workspace when that access mode is allowed by the gateway.

### Model failures

After a model request fails and automatic retries stop, the WebUI shows the failure category. Use **Continue** to resume from the saved conversation, or open model settings to change the model or correct its authorization. Review completed work before continuing: saved tool results are retained, but the model can choose to call tools again. Continuing does not resend the original message. Sending a new message or dismissing the notice clears the pending decision. Saved recovery decisions remain available after a refresh or gateway restart; temporary chats still follow their normal lifetime.

### Delegated work

When nanobot delegates work to subagents, a work group appears under the request that started it. Progress continues to update after the main reply finishes. Completed tasks stay available for inspection, and refreshing or reopening the WebUI restores saved progress and results without restarting the work.

Work groups follow the browser's **Activity details** preference: **Auto** opens running work and folds it when all tasks finish; **Expanded** keeps it open by default. You can also expand or fold a group manually to check individual outcomes, including failures and partial results.

Select a task for its read-only conversation and tool activity. Closing the details leaves it running; its stop button cancels only that task. Give follow-up instructions to nanobot in the main conversation.

These controls appear when the connected host supports subagent tasks. See [Subagents](./concepts.md#subagents) for cancellation, saved history, and gateway restart behavior.

## Temporary Chats

Start **New topic → Temporary chat** for a conversation that should not be added to topic history or long-term memory.

You can keep more than one temporary chat open and switch between them under **Temporary chats** in the sidebar while the current WebUI connection remains open. Reloading or closing the page, restarting the gateway, or losing the WebSocket connection ends all of them. They cannot be recovered afterward.

Temporary chats do not create saved files for oversized text tool results; these stay in memory and are truncated to the configured tool-result limit. Tool-call arguments and execution-error details are hidden from the built-in tool logs, while tool activity remains visible in the current chat.

Temporary does not mean consequence-free. Requests still go to the configured model provider, and tools can still change files, run commands, or affect external services. Files and image artifacts created or exported by tools (including images returned by MCP tools) are not erased when the chat closes. Temporary chats always use the default workspace in Restricted mode; the project picker and Full Access are unavailable. Commands and tools that create durable goals, automations, or subagent work are also unavailable. Use a regular topic when you need reusable context, scheduled work, or a result you must retain.

## Workspace and Access

Use the workspace picker to browse folders on the connected nanobot host, enter an absolute path, or return to recent and starred projects; favorites persist across gateway restarts. The host name appears above saved locations. Project paths refer to that machine, not the browser's filesystem.

Browsing does not change the topic's workspace until you choose **Confirm**. **Filter this folder** searches only the current directory. **Cmd/Ctrl+Shift+G** opens host-path entry, with Tab completion; **Last visited folder** returns to the previous location.

Manual path entry remains available when the connected host does not support directory browsing. The host validates the selected path and access policy.

Selecting a project does not replace the configured agent workspace. The two paths have different responsibilities:

| Selected project provides | Agent workspace continues to provide |
|---|---|
| Project `AGENTS.md` | `SOUL.md` and `USER.md` |
| Relative file paths and shell working directory | Long-term memory and history |
| The normal read/write boundary in Restricted mode | Custom skills and instance state |

A new topic separates conversation history; a project selection changes the file working directory. Neither creates a separate long-term memory store. Project switching can therefore carry preferences and facts learned in other topics into the new project. Use [separate instances](./multiple-instances.md) when client or user data must stay separate; see [Memory](./memory.md) for how shared memory is maintained.

Project-local `SOUL.md` and `USER.md` files are ignored, and the agent workspace's `AGENTS.md` is not inherited by a separately selected project. When the selected project is the configured agent workspace, both roles naturally use the same directory.

The access control in the composer controls the local capability level for the chat. It does not bypass your gateway, provider, shell sandbox, or operating system configuration; it only selects among the capabilities that are already available to the current topic.

In Restricted mode, ordinary file and shell work stays inside the selected project. To preserve agent continuity, filesystem/search tools receive narrow, read-only access to built-in skills, custom skills in the agent workspace, and the exact agent `memory/history.jsonl` file. This does not grant access to neighboring memory or profile files, and it does not allow writes outside the selected project. These tool exceptions do not broaden the browser's file preview boundary.

## Composer

The composer supports text, attachments (images, documents, and videos), slash commands and `@` mentions. With voice transcription configured, the empty composer offers voice input; transcription is added to the draft before sending.

Images appear as thumbnails above the draft. Hover over a thumbnail for its filename and size; use its top-right × to remove it before sending. Documents and videos keep their file cards, and attachment errors remain visible.

Choose or drop MP4, WebM, or MOV videos into the composer (one per message, up to 20 MiB per upload). You can play them in WebUI; the Agent cannot directly analyze their contents yet.

To attach a file on the connected nanobot host, paste its path on its own. Quoted paths and spaces are supported; relative paths start from the topic's workspace. The topic's access permissions apply. Path references do not upload or copy the file and have no file-size or combined-size limit; supported formats and attachment counts still apply. If attaching fails, the text stays in your draft.

Files attached by path reflect changes to the original file and become unavailable if it is moved or deleted. Removing an attachment or deleting a topic does not delete the original.

To reference another topic, type or paste its complete handle (such as `@luma`), choose it from the `@` menu, or drag it from the sidebar into the composer. Recognized handles are highlighted; unknown handles remain plain text. You can reference up to eight different topics in one message.

Ask nanobot to find, read, or send messages to other saved topics, including those in other projects. For example, “Summarize @luma” or “Send this update to @luma.” Mentioning a topic alone does not send a message to it.

On touch-primary phones and tablets, **Enter** inserts a newline; tap the send arrow to submit. This also applies when a coarse-pointer tablet has a hardware keyboard attached. On desktop, **Enter** sends and **Shift+Enter** adds a newline. An open slash-command or mention menu takes precedence: Enter selects its item.

During a response, desktop Enter appends input to one waiting message, preserving order, attachments and references. It sends when the response finishes. **Send now** or Enter on an empty input sends it immediately as guidance; the send arrow submits the waiting content together with any draft. **Edit message** and **Delete message** act on the whole waiting message. Additions that exceed limits stay in the input. Stopping a turn or a failed send preserves the waiting message for manual sending.

Automatic sending continues across topic switches and short reconnects while the page stays live. Reloading, reopening, leaving the page, or the browser freezing it restores waiting content for manual sending; choose **Send now** or edit and send it when ready.

For image generation, configure an image provider first and then use the WebUI image mode from the composer. See [`image-generation.md`](./image-generation.md) for provider setup and output behavior.

## Channels

**Channels** provides credential or QR-based setup, connection validation, and restart guidance. Missing channel support can be installed from a local WebUI. When newly installed support needs a restart, select the restart icon in that channel's row before continuing setup.

The platform itself may still require you to create a bot, enable event permissions, copy a token, or configure a webhook. Use [`chat-apps.md`](./chat-apps.md) for those platform-side prerequisites and for manual JSON/reference options.

Test a new channel with a private DM. When a supported channel sends a pairing code, the WebUI surfaces the pending request so you can approve the sender. Keep access narrow; do not use a wildcard allowlist unless public access is intentional.

## Apps

**Apps → Ready** lists capabilities available for use:

- **Agent Plugins** are local packages that can bundle skills, MCP servers, or both. A package under `<workspace>/plugins/` is installed but remains inactive until you enable it in Apps.
- **CLI Apps** are command-line tool adapters on the nanobot host. Install and enable an adapter before attaching it to a turn.
- **MCP** lists Model Context Protocol servers. Presets provide known configurations, and the **Add MCP server** panel accepts stdio, HTTP, and SSE servers. Custom HTTP/SSE servers can use no authentication, OAuth, or request headers. After saving an OAuth server, choose **Connect** to open its sign-in page. Presets such as Xmind, Notion, and Linear already use OAuth. HTTPS and localhost WebUIs return automatically; a remote plain-HTTP WebUI shows one field for pasting the complete localhost callback URL.

CLI Apps run with a limited environment that excludes provider API keys. On Unix, they inherit `XDG_RUNTIME_DIR` when it is set in the gateway's environment, so desktop CLIs such as Obsidian can locate the running application. Start the gateway in the same desktop session as the app to inherit that runtime directory.

Manage optional runtime support from **System**, **Models**, or **Web**, or use [`nanobot plugins`](./cli-reference.md#optional-features). That command manages runtime extras, not Agent Plugin packages. PDF and common Office attachment readers require no setup.

Keyless hosted presets include **Firecrawl** for search, scraping, crawling and extraction, and **Parallel Search** for `web_search` and `web_fetch`. They are optional MCP tools and do not change the built-in web search provider.

After a CLI App or MCP server is available, mention it from the composer with `@` to attach that tool to the next message. Plugin-provided skills participate in normal skill discovery and can be invoked with `$skill-name`.

## Skills

Open **Skills → Installed** to review built-in and workspace-provided skills. You can search and filter them, inspect their instructions and setup requirements, enable or disable them, and delete workspace skills you no longer want.

Open **Skills → Discover** to browse or search skills from skills.sh and SkillHub. A marketplace skill is copied into the active agent workspace after you confirm the installation. skills.sh installation requires Node.js with `npx`; SkillHub installation does not.

Marketplace skills are third-party instructions and may include executable scripts. Review the source and instructions before installing one, and enable only skills you trust with the same files, tools, and credentials available to your agent.

## Automations

Automations are agent turns that run later in a linked topic. Create them from the topic or channel where they are supposed to run so nanobot keeps the correct target context. When an automation runs, it normally delivers the result back to that topic.

For the full automation model, creation flow, trigger CLI usage, and delivery semantics, see [`automations.md`](./automations.md).

There are two user-facing automation types:

- Scheduled automations, created by the agent's cron tool, run at a time, interval, or cron expression.
- Local triggers, created with `/trigger <name>`, run when you call a local command such as `nanobot trigger trg_8K4P2Q9X "Review PR #4502"`.

For recurring background checks that should stay quiet unless there is something useful to report, use the protected heartbeat job by editing `HEARTBEAT.md` instead of creating a chat automation.

The Automations view manages user-created jobs and can run scheduled jobs immediately. Protected system jobs are read-only.

Search accepts plain text and field filters such as `name:backup`, `chat:WeChat`, `schedule:09:30`, `cron:"0 23 * * *"`, `trigger`, and `status:paused`.

An automation without a linked topic cannot be enabled or run from the WebUI, because nanobot would not know where to deliver the scheduled turn. Recreate it from the target topic or channel so the automation has complete context.

Local triggers do not have a WebUI "Run now" action because each run needs a message. Use the copied `nanobot trigger ...` command and replace `"message"` with the content that should be delivered.

## Settings

Runtime settings may require a gateway restart; the WebUI marks those controls.

**Appearance → Local preferences** applies immediately to the current browser without changing gateway configuration. **Reading text size** adjusts conversation text, Markdown, code and the input, but not navigation or toolbars; standard is the default.

## LAN Access

To open the WebUI from another device on the same network, bind the WebSocket channel to all interfaces and set a token or token issue secret:

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

The gateway refuses to start with `host` set to `"0.0.0.0"` unless `token` or `tokenIssueSecret` is configured. After the gateway starts, open `http://<your-ip>:8765` from the other device and enter the secret in the login form.

Plain HTTP is enough for basic WebUI access, but browsers expose microphone capture only in secure contexts. Voice input works on same-machine localhost; from another device, serve the WebUI over HTTPS with a certificate that device trusts. Configure [`sslCertfile` and `sslKeyfile`](./websocket.md#tlsssl) on the WebSocket channel and open `https://<your-host>:8765`, or terminate HTTPS at a reverse proxy and use that proxy's HTTPS URL.

Remote WebUI clients with a valid token can view and use Apps and installed skills. Actions that install missing nanobot support packages or third-party marketplace skills are blocked by default. To let trusted remote administrators perform those installations through the WebUI, opt in explicitly:

<details>
<summary>Manual configuration</summary>

```json
{
  "tools": {
    "webuiAllowRemotePackageInstall": true
  }
}
```

</details>

Enable remote installation only for a private deployment whose users are trusted to change the Python environment and install skill instructions or scripts. Reverse-proxy and tunnel deployments count as remote access.

Optional feature installs use pip's configured package index, including `PIP_INDEX_URL`. skills.sh marketplace installs use `npx` instead.

## Troubleshooting

### Connection checks

If the page does not open, check these in order:

1. `nanobot agent -m "Hello!"` works in the same Python environment.
2. `~/.nanobot/config.json` does not explicitly set `channels.websocket.enabled` to `false`.
3. `nanobot gateway` is still running.
4. You are using the WebUI port (`8765` by default), not the health port (`18790` by default).
5. LAN access uses `host: "0.0.0.0"` and a token or token issue secret.

For detailed diagnostics, see [`troubleshooting.md#webui-problems`](./troubleshooting.md#webui-problems). For frontend development, see [`../webui/README.md`](../webui/README.md).
