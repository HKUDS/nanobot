# nanobot Terminal UI

The terminal UI is a TypeScript client for nanobot's existing WebSocket gateway. It owns presentation and input only; the Python gateway remains the single implementation of sessions, the agent loop, tools, memory, and security policy.

```bash
bun install --cwd tui
bun run --cwd tui check
bun run --cwd tui test
bun run --cwd tui build
```

`nanobot agent` launches this client, leases the shared local gateway or starts it on demand, and passes the local bootstrap endpoint through environment variables. The client paints before gateway readiness, retries bootstrap in the background, and obtains fresh WebSocket and REST credentials for each connection. Other terminals and the WebUI keep that gateway alive; the final interactive launcher to exit releases the on-demand process. `/detach` closes the TUI after promoting the gateway to persistent background mode, keeping any active agent turn running without clients; the restored terminal prints the exact stop command for that config and explicit workspace. `nanobot gateway --background` can start or promote it persistently before opening a client. Source checkouts automatically align dependencies with `bun.lock` before launch; released installs use a version-matched, checksum-verified archive that keeps the executable together with its licenses, notices, corresponding application source, source offer, and relinking instructions. Startup fails explicitly if the native client is unavailable. The legacy Python prompt is only selected with `nanobot agent --classic`.

Standalone terminals use OpenTUI's retained full-screen layout: the transcript reflows with the terminal while the composer stays fixed at the bottom. Mouse and keyboard scrolling operate inside the transcript, and leaving the TUI restores the previous terminal screen.

Assistant math written with `$...$`, `$$...$$`, `\\(...\\)`, or `\\[...\\]` is presented as
Unicode plain text so formulas remain readable in terminals without a math renderer. Currency and
LaTeX inside inline or fenced code remain literal.

## Herdr host mode

When Herdr supplies `HERDR_ENV=1` and `HERDR_PANE_ID`, nanobot becomes a quiet hosted client. It uses OpenTUI's main-screen mode instead of hiding the whole run in a temporary alternate screen, removes the launch card and persistent session/model/task chrome, and keeps only the transcript, compact progress, and composer. Herdr remains responsible for workspace, tab, pane, task, and attention navigation, while nanobot keeps its application-level session, new-chat, and branch commands.

The TUI reports its WebSocket session ID, model, Git branch, workspace, last task, and current action through Herdr's supported pane CLI. Sending work reports `working`; a persisted explicit nanobot goal block reports `blocked`; a completed turn reports `idle`; exit releases lifecycle authority. The gateway session remains the durable transcript and resume path. Standalone terminals keep the richer full-screen navigation described below.

The model preset and workspace access labels above the composer are live controls. Click either
label, then click a choice; arrow keys, `Enter`, and `Esc` provide the same flow without a mouse.
Changes reuse the gateway's normal model command and workspace policy checks.

When you scroll away from the latest output, the scrollbar and `Ctrl+End` hint appear only until
you return to the bottom. Large pastes are represented by a short editable placeholder in the
composer; nanobot sends the original text unchanged.

While a turn is running, the composer remains available for steering and uses `Steer this turn…`
as its prompt. The footer shows the lifecycle and elapsed time without repeating the latest tool
activity already visible in the transcript.

Type `/` to discover slash commands published by the connected gateway. Use the arrow keys
to move, `Tab` to complete, and `Esc` to close the menu.

Use `/config` to edit the complete nanobot configuration without leaving the agent. The first
view contains only workspace, model, provider, and credentials; domain pages keep low-frequency
settings under an explicit Advanced row, while `/` inside the editor searches every schema and
plugin field. Changes remain staged until `Ctrl+S`, secrets never render in the terminal, and
`Esc` asks before discarding unsaved work.

Type `@` to complete installed CLI apps, configured MCP servers, or saved sessions through the
same gateway metadata used by the WebUI. While nanobot is working, `Enter` steers the current
turn, `Tab` queues a follow-up for the next turn, and `Option+Up` on macOS (`Alt+Up` on
Windows/Linux) returns the latest queued message to the composer for editing. The pending queue
stays visible above the composer.
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
