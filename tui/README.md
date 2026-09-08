# nanobot Terminal UI

The terminal UI is a TypeScript client for nanobot's existing WebSocket gateway. It owns presentation and input only; the Python gateway remains the single implementation of sessions, the agent loop, tools, memory, and security policy.

```bash
bun install --cwd tui
bun run --cwd tui check
bun run --cwd tui test
bun run --cwd tui build
```

`nanobot` (or the explicit `nanobot agent` form) launches this client, leases the shared local gateway or starts it on demand, and passes the local bootstrap endpoint through environment variables. The client paints before gateway readiness, retries bootstrap in the background, and obtains fresh WebSocket and REST credentials for each connection. Other terminals and the WebUI keep that gateway alive; the final interactive launcher to exit releases the on-demand process. `/detach` closes the TUI after promoting the gateway to persistent background mode, keeping any active agent turn running without clients; the restored terminal prints the exact stop command for that config and explicit workspace. `nanobot gateway --background` can start or promote it persistently before opening a client. Source checkouts automatically align dependencies with `bun.lock` before launch; released installs use a version-matched, checksum-verified archive that keeps the executable together with its licenses, notices, corresponding application source, source offer, and relinking instructions. Startup fails explicitly if the native client is unavailable. The legacy Python prompt is selected with `nanobot --classic` or `nanobot agent --classic`.

The TUI uses OpenTUI's retained full-screen layout: the transcript reflows with the terminal while the composer stays fixed at the bottom. Mouse and keyboard scrolling operate inside the transcript, and leaving the TUI restores the previous terminal screen.

Assistant math written with `$...$`, `$$...$$`, `\\(...\\)`, or `\\[...\\]` is presented as
Unicode plain text so formulas remain readable in terminals without a math renderer. Currency and
LaTeX inside inline or fenced code remain literal.

## Herdr pane titles

When Herdr supplies `HERDR_ENV=1` and `HERDR_PANE_ID`, nanobot keeps the same full-screen layout, controls, and navigation available in any other terminal. Its only host-specific behavior is reporting the latest user task as the Herdr pane title through the supported pane CLI. Creating a new chat, switching to a chat without a task, and exiting the TUI clear that title. Nanobot does not report agent lifecycle, session, model, Git branch, workspace, or action metadata to Herdr.

The model preset and workspace access labels above the composer are live controls. Click either
label, then click a choice; arrow keys, `Enter`, and `Esc` provide the same flow without a mouse.
Changes reuse the gateway's normal model command and workspace policy checks.

When you scroll away from the latest output, the scrollbar and `Ctrl+End` hint appear only until
you return to the bottom. Large pastes are represented by a short editable placeholder in the
composer; nanobot sends the original text unchanged. Press `Ctrl+V` or `Alt+V` while the composer
is focused to attach an image from the system clipboard. Image bytes stay behind removable
`[Image #n]` placeholders until the message is sent; each placeholder behaves as one unit, and
deleting it removes its image.

While nanobot is working, the composer prompt becomes
`Enter send now · Tab send next`; narrow terminals shorten it to `Enter now · Tab next`.
The footer shows progress and elapsed time without repeating the latest tool activity already
visible in the transcript.

Type `/` to discover slash commands published by the connected gateway. Use the arrow keys
to move, `Tab` to complete, and `Esc` to close the menu.

Use `/config` or `nanobot onboard --wizard` to open Quick start. Choose **Sign in with an
account**, **Use an API key**, or **Connect a local model**. Type to search providers and models;
results appear eight at a time. If your default already has credentials, you can continue chatting
or configure a preset without repeating sign-in.

Opening the account list checks saved credentials against each provider's live authenticated model
catalog in the background. Status shows **Checking…**, **Available**, **Sign in again**,
**Network error**, or **Check failed**. These checks bypass cached and built-in model lists,
refresh tokens when needed, and send no chat messages. **Reload providers** repeats the checks.
An accepted account does not guarantee access or quota for every model; test the saved preset to
verify a model reply.

Browser sign-in opens automatically. Codex receives its callback on the terminal machine;
Copilot displays a device code and waits for approval. Grok asks for the authorization code.
**Browser didn't open?** exposes copy-link, manual callback, and restart options. If the local
callback port is unavailable, the manual callback input appears automatically.

API credentials are saved when you select **Save connection and configure preset**; OAuth credentials
are saved when authorization completes. Both routes then open **Configure preset**. Name the preset,
choose its model, and optionally adjust its output token limit, context window, temperature, and
reasoning effort under **Generation settings**. You can also explicitly select an existing preset
to edit. **Use as default** controls whether new chats select the saved preset; other presets and
legacy model fields are preserved.

Save the preset, then optionally select **Send a test message**. This sends one short request using
the saved preset's model and generation settings, with output capped at 256 tokens; provider charges
may apply.
Saving credentials alone is not reported as a successful model check. A failed check keeps the
saved configuration and offers connection and model changes. **Start a new chat** uses the saved
default and preserves the previous conversation.

**Advanced settings** contains workspace, channel, tool, and other settings. `/` searches every
schema and plugin field outside Quick start. Advanced edits remain staged until `Ctrl+S`; `Esc`
asks before discarding unsaved work. Secret input is hidden. `Ctrl+C` exits configuration even
while typing, saving, or waiting for sign-in; unsaved edits are discarded and login listeners and
polling are stopped.

Type `@` to complete installed CLI apps, configured MCP servers, or saved sessions through the
same gateway metadata used by the WebUI. While nanobot is working, `Enter` sends immediately,
`Tab` waits until the current response is finished, and `Option+Up` on macOS (`Alt+Up` on
Windows/Linux) returns the latest waiting message to the composer for editing. Waiting messages
stay visible above the composer.
Use `Shift+Enter` for a newline; `Ctrl+J` is the universal fallback when a terminal cannot
distinguish modified Enter keys. `Alt+Enter` and `Ctrl+Enter` are also accepted when distinguishable.
Unsent prompts return to the composer if the turn stops or fails.

Use `/sessions` to search and switch persisted conversations without leaving the terminal.
`/new-chat` preserves the current conversation and starts another one; nanobot's existing `/new`
command keeps its cross-channel behavior and resets the current chat. Each launch starts a new
session using the launch directory as its workspace; `--session` selects an existing session and
`--workspace` overrides the launch directory. On exit, the restored terminal prints a ready-to-run
`nanobot agent --session ...` command that resumes the current session. When earlier transcript
pages exist, press `PageUp` at the top to load them in place.

The native client accepts bare WebSocket chat IDs or `websocket:<id>` selectors. Use
`nanobot agent --classic --session <channel:id>` to resume a session owned by another channel;
the TUI never silently maps one channel's identity into the WebSocket namespace.

Sessions are live across clients: if two terminals or the WebUI attach to the same session, an
accepted user message and the resulting agent/tool stream appear on every attached client while
the gateway executes the input only once.

`/branch` creates a new saved conversation from a completed reply without changing the source
session. The picker uses durable history indices, so paginated transcripts branch at the selected
turn rather than the currently visible row.

`/context` explains the session-owned material available for the next agent turn: the compacted
summary, replayable raw suffix, and an estimated token count. It deliberately does not expose
private reasoning and does not pretend to be the complete model prompt; workspace instructions,
memory, and skills are assembled separately by the Python runtime.

`/diff` opens the latest turn's file changes in a full-screen unified diff. Use `Left`/`Right`
to switch edits, `PageUp`/`PageDown` or `Home`/`End` to navigate, and `Esc` to return to chat.
The gateway remains the source of the patch; the TUI never rereads workspace files to rebuild it.
The footer reports provider token/cache usage when available, and tool activity uses compact,
tool-specific summaries while retaining the full event history behind `Ctrl+O`.
