# nanobot Terminal UI

The terminal UI is a TypeScript client for nanobot's existing WebSocket gateway. It owns presentation and input only; the Python gateway remains the single implementation of sessions, the agent loop, tools, memory, and security policy.

```bash
bun install --cwd tui
bun run --cwd tui check
bun run --cwd tui test
bun run --cwd tui build
```

`nanobot agent` launches this client, attaches to an existing local gateway or leases one for the process lifetime, and passes an authenticated local endpoint through environment variables. Source checkouts automatically align dependencies with `bun.lock` before launch; released installs use a version-matched, checksum-verified sidecar. Startup fails explicitly if the native client is unavailable. The legacy Python prompt is only selected with `nanobot agent --classic`.

The renderer uses OpenTUI's retained full-screen layout: the transcript reflows with the terminal while the composer stays fixed at the bottom. Mouse and keyboard scrolling operate inside the transcript, and leaving the TUI restores the previous terminal screen.

When you scroll away from the latest output, the scrollbar and `Ctrl+End` hint appear only until
you return to the bottom. Large pastes are represented by a short editable placeholder in the
composer; nanobot sends the original text unchanged.

Type `/` to discover slash commands published by the connected gateway. Use the arrow keys
to move, `Tab` to complete, and `Esc` to close the menu.

Type `@` to complete installed CLI apps, configured MCP servers, or saved sessions through the
same gateway metadata used by the WebUI. While nanobot is working, `Enter` steers the current
turn, `Tab` queues a follow-up for the next turn, and `Alt+Up` returns the latest queued message
to the composer for editing. The pending queue stays visible above the composer.
Use `Ctrl+J` for a newline; `Shift+Enter`, `Alt+Enter`, and `Ctrl+Enter` are also accepted when
the terminal can distinguish them.
Unsent prompts return to the composer if the turn stops or fails.

Use `/sessions` to search and switch persisted conversations without leaving the terminal.
`/new-chat` preserves the current conversation and starts another one; nanobot's existing `/new`
command keeps its cross-channel behavior and resets the current chat. The next launch returns to
the last session unless `--session` selects another one. When earlier transcript pages exist,
press `PageUp` at the top to load them in place.

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
