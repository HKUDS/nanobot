# Common Gotchas

## Channel dependencies for strict type checking

Channel dependencies come from channel package manifests, outside the main extras. Reproduce CI's setup with `uv sync --all-extras --dev`, then `uv run --no-sync python -m scripts.install_channel_dependencies --all-channels`. Keep `--no-sync` on subsequent `uv run` commands so syncing does not remove those dependencies. See `.github/workflows/ci.yml` for checks.

## Channel-owned UI and WebUI transport

Channels can own frontend code in `nanobot/channels/*/webui/` and tests in `nanobot/channels/*/tests/`, including `tests/webui/`. The WebUI's lint and test configurations include those frontend paths. Do not assume all channel tests live under the root `tests/` or all frontend code lives under `webui/`.

Vite proxies `/api`, `/webui`, and `/auth`; the application's WebSocket connects directly to the gateway. `NANOBOT_API_URL` sets the HTTP proxy target, whose default is `http://127.0.0.1:8765`. See `webui/vite.config.ts`.

## Config `${VAR}` References

`nanobot/config/loader.py` loads and validates the config; `resolve_config_env_vars` resolves `${VAR}` references before runtime use. This is not shell-like default-value syntax. Missing referenced variables raise `ConfigLoadError` with field locations; invalid existing config files also raise `ConfigLoadError`. Defaults are created when the config file is absent, not as recovery from an invalid file.

## Windows Compatibility

nanobot explicitly supports Windows. Key differences to keep in mind:
- `ExecTool` defaults to PowerShell on Windows (`pwsh` when available, otherwise Windows PowerShell); pass `shell="cmd"` for cmd.exe syntax or cmd built-ins (`shell.py`).
- `nanobot/cli/entry.py` configures Windows console output as UTF-8 before dispatch to handle emoji and multilingual input.
- MCP stdio server commands are normalized for Windows path separators (`mcp.py`).

## Prompt Templates

Agent system prompts and scenario-specific instructions live in `nanobot/templates/`, including `agent/identity.md` and `agent/platform_policy.md`; workspace defaults include `AGENTS.md`, `HEARTBEAT.md`, and `SOUL.md`. Prompt rendering is handled by `nanobot/utils/prompt_templates.py`. Changing these files alters agent behavior as directly as changing Python code.

The repository's root `AGENTS.md` guides coding agents; `nanobot/templates/AGENTS.md` is a default for nanobot workspaces. `nanobot/agent/context.py` loads project `AGENTS.md` and global `SOUL.md`/`USER.md`, skipping unchanged bundled `AGENTS.md` and `USER.md` defaults. It does not implement Codex's ancestor-directory instruction chain.

Tool descriptions, skills, and replayed session history also shape model behavior. Treat changes to those surfaces like runtime code: keep them focused, verify the affected contract, and avoid teaching the model to repeat internal markers, local paths, or tool-call text. Add a regression test when it proves a reachable failure that existing coverage does not address.

## Context Pollution Persists

Anything written into memory, session history, or prompt inputs can be replayed into future LLM calls. Metadata such as timestamps, local media paths, tool-call echoes, and raw fallback dumps must be bounded and sanitized before they become examples for the model to imitate.

## Skills as Extension Point

Built-in skills live in `nanobot/skills/` (markdown + YAML frontmatter format). Agent capabilities that are "know-how" rather than code should be added as skills, not hardcoded into the agent loop. External skills can be published to and installed from ClawHub.

## Persistence and durability

`nanobot/agent/memory.py` owns the memory journal `memory/history.jsonl`; ordinary entries are appended under a lock, without explicit fsync. Full journal rewrites use `atomic_write_lines` with its default file and directory fsync. Preserve that atomic replacement path rather than truncating the live journal in place.

Conversation history belongs to `nanobot/session/manager.py`. Session saves use atomic replacement, with fsync controlled by the caller; the default is `False`, while durable shutdown and other explicit durability paths request `True`. Preserve the distinction between atomic visibility and crash durability, and retain locks and explicit fsync on paths that require them.
