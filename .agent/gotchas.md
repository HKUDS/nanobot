# Common Gotchas

## Do not use `ruff format`

`CONTRIBUTING.md` mentions `ruff format`, but **do not run it** — it destroys git blame history. Only `ruff check` should be used.

## Config `${VAR}` References

`config/loader.py` resolves `${VAR}` patterns in `config.json` at load time. This is **not** a shell-like default-value syntax. If the environment variable is missing, `load_config` raises `ValueError` and the agent falls back to default configuration.

Example valid usage:
```json
{ "providers": { "openrouter": { "apiKey": "${OPENROUTER_KEY}" } } }
```

## Windows Compatibility

nanobot explicitly supports Windows. Key differences to keep in mind:
- `ExecTool` uses `cmd /c` on Windows instead of `sh -c` (`shell.py`).
- `cli/commands.py` forces `sys.stdout`/`stderr` to UTF-8 on startup to handle emoji and multilingual input.
- MCP stdio server commands are normalized for Windows path separators (`mcp.py`).
- Always use `pathlib.Path` for path manipulation; do not assume `/` separators.

## Prompt Templates

Agent system prompts and scenario-specific instructions live in `nanobot/templates/` as Jinja2 markdown files (`identity.md`, `platform_policy.md`, `HEARTBEAT.md`, `SOUL.md`, etc.). Changing these files alters agent behavior as directly as changing Python code. They are loaded by `utils/prompt_templates.py`.

Tool descriptions, skills, and replayed session history also shape model behavior. Treat changes to those surfaces like runtime code: keep them narrow, add a focused regression test when possible, and avoid teaching the model to repeat internal markers, local paths, or tool-call text.

## Context Pollution Persists

Anything written into memory, session history, or prompt inputs can be replayed into future LLM calls. Metadata such as timestamps, local media paths, tool-call echoes, and raw fallback dumps must be bounded and sanitized before they become examples for the model to imitate.

## Heartbeat Virtual Tool Call

The heartbeat service (`heartbeat/service.py`) does not parse free-text LLM output. Instead, it injects a virtual `heartbeat` tool with `action: skip | run` into the conversation. Phase 1 is a structured decision; Phase 2 executes only on `run`. When adding new periodic background checks, follow this virtual-tool-call pattern rather than string matching.

## Skills as Extension Point

Built-in skills live in `nanobot/skills/` (markdown + YAML frontmatter format). Agent capabilities that are "know-how" rather than code should be added as skills, not hardcoded into the agent loop. External skills can be published to and installed from ClawHub.

## Atomic Session Writes

`agent/memory.py` writes `history.jsonl` atomically (temp file + fsync + rename + directory fsync). This guarantees durability across crashes. Do not replace this with a plain `open(..., "w")` write.
