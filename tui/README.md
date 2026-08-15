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

Use `/sessions` to search and switch persisted conversations without leaving the terminal.
`/new-chat` preserves the current conversation and starts another one; nanobot's existing `/new`
command keeps its cross-channel behavior and resets the current chat. The next launch returns to
the last session unless `--session` selects another one. When earlier transcript pages exist,
press `PageUp` at the top to load them in place.

`/context` explains the session-owned material available for the next agent turn: the compacted
summary, replayable raw suffix, and an estimated token count. It deliberately does not expose
private reasoning and does not pretend to be the complete model prompt; workspace instructions,
memory, and skills are assembled separately by the Python runtime.

`/diff` opens the latest turn's file changes in a full-screen unified diff. Use `Left`/`Right`
to switch edits, `PageUp`/`PageDown` or `Home`/`End` to navigate, and `Esc` to return to chat.
The gateway remains the source of the patch; the TUI never rereads workspace files to rebuild it.
