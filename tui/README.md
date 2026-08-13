# nanobot Terminal UI

The terminal UI is a TypeScript client for nanobot's existing WebSocket gateway. It owns presentation and input only; the Python gateway remains the single implementation of sessions, the agent loop, tools, memory, and security policy.

```bash
bun install --cwd tui
bun run --cwd tui check
bun run --cwd tui test
bun run --cwd tui build
```

`nanobot agent` launches this client, attaches to an existing local gateway or leases one for the process lifetime, and passes an authenticated local endpoint through environment variables. Use `nanobot agent --classic` to run the legacy Python prompt.

The renderer uses OpenTUI's retained full-screen layout: the transcript reflows with the terminal while the composer stays fixed at the bottom. Mouse and keyboard scrolling operate inside the transcript, and leaving the TUI restores the previous terminal screen.

Type `/` to discover slash commands published by the connected gateway. Use the arrow keys
to move, `Tab` to complete, and `Esc` to close the menu.
