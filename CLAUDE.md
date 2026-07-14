# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Note: this repo previously delegated to `AGENTS.md` via `@AGENTS.md`. The full
> agent guidance now lives here; `AGENTS.md` is kept as a near-duplicate for
> other AI tooling. If you edit one, keep the other in sync.

nanobot is a lightweight, open-source AI agent framework (Python 3.11+, asyncio)
with a React/TypeScript WebUI. PyPI package name is **`nanobot-ai`**; the Python
package is the nested `nanobot/` directory (the repo root is *not* the package
root).

## Development Commands

```bash
# Python — editable install with dev deps
pip install -e ".[dev]"

# Tests (pytest, asyncio_mode=auto, testpaths=["tests"])
pytest                                    # full suite
pytest tests/test_openai_api.py           # one file
pytest tests/test_openai_api.py::test_fn  # one test
pytest --cov=nanobot                      # coverage (fail_under=75)

# Lint — ONLY ruff check. NEVER run `ruff format` (destroys git blame)
ruff check nanobot/                        # line-length 100, rules E,F,I,N,W (E501 ignored)
ruff check --fix nanobot/                  # auto-fix import sorting etc.

# Gateway / CLI
nanobot gateway                            # starts the API + WebSocket gateway (:8765)
nanobot                                    # interactive CLI / onboarding

# WebUI (bun required) — dev server proxies /api,/webui,/auth + WS to gateway
cd webui && bun run dev                    # or: NANOBOT_API_URL=... bun run dev
cd webui && bun run build                  # outputs to ../nanobot/web/dist (shipped in wheel)
cd webui && bun run test
```

To get a clean topic branch (from `CONTRIBUTING.md`):
```bash
git fetch upstream && git switch main && git pull --ff-only upstream main && git switch -c topic
```

## High-Level Architecture

**Core data flow** — an async `MessageBus` (`nanobot/bus/queue.py`) decouples
chat channels from the agent core:

1. **Channels** (`nanobot/channels/`) receive platform messages → publish `InboundMessage`.
2. **`AgentLoop`** (`nanobot/agent/loop.py`) consumes inbound messages, builds context, owns session keys/hooks/runtime-event fan-out.
3. **`AgentRunner`** (`nanobot/agent/runner.py`) runs the actual multi-turn LLM loop: provider call → tool calls → tool execution → streamed response.
4. Responses are published as `OutboundMessage` events back to the originating channel.

`loop.py` + `runner.py` are the **critical core path** — keep changes there minimal and justified. Most new capabilities belong at the edges (a channel, a tool, a skill, or an MCP server).

**Key subsystems** (all under `nanobot/`):
- **providers/** — LLM providers (Anthropic, OpenAI-compat, OpenAI Responses API, Azure, Bedrock, GitHub Copilot, Codex, fallback) on a common `base.py`; `factory.py` + `registry.py` handle instantiation and model discovery. Image generation + audio transcription included.
- **channels/** — platform adapters (Telegram, Discord, Slack, Feishu, Matrix, WhatsApp, QQ/napcat, WeChat, WeCom, DingTalk, Email, MoChat, MS Teams, Mattermost, WebSocket). Auto-discovered via `pkgutil` scan + `entry-points`. `manager.py` coordinates.
- **agent/tools/** — agent capabilities exposed to the LLM: filesystem, shell (`ExecTool`), web search/fetch, MCP, cron, notebooks, subagent spawn, long-running tasks/goals (`long_task.py`), image gen, self-modification. Auto-discovered via `pkgutil` + entry-points; `registry.py` is the registry.
- **agent/memory.py** — session history persistence with Dream two-phase consolidation. **Atomic writes** (temp + fsync + rename + dir fsync) — never replace with plain `open(...,"w")`.
- **session/** — per-session history, context compaction, TTL auto-compaction (`manager.py`), sustained goal state (`goal_state.py`).
- **config/** — Pydantic models in `schema.py`, loaded from `~/.nanobot/config.json` (`loader.py`). JSON uses camelCase aliases; `${VAR}` is env-substitution (raises `ValueError` if missing — **not** a default-value syntax).
- **api/server.py** — OpenAI-compatible HTTP API (`/v1/chat/completions`, `/v1/models`).
- **command/** — slash-command routing + built-in handlers.
- **security/** — PTH file guard + network guards; activated at CLI entry.
- **skills/** — built-in skills (markdown + YAML frontmatter), the preferred extension point for "know-how" rather than code.
- **templates/** — Jinja2 `.md` prompts (`identity.md`, `SOUL.md`, `HEARTBEAT.md`, `platform_policy.md`). **Editing these changes agent behavior as directly as editing Python** — treat like runtime code.

**Entry points**: CLI = `nanobot/cli/commands.py` (declared in `[project.scripts]`); Python SDK = `nanobot/nanobot.py`.

## Architecture Constraints (from `.agent/design.md`)

- **Core stays small; extend at the edges.** If a feature can live in a channel adapter, tool, skill, or MCP server, do not inline it into the agent loop.
- **Runtime-event fan-out boundary:** `AgentLoop` may publish generic events from `nanobot.bus.runtime_events`, but WebUI/WebSocket wire details (`_turn_end`, `_goal_status`, title refresh, goal-state sync) belong in `session/webui_turns.WebuiTurnCoordinator` or the channel adapter.
- **Prefer duplication over premature abstraction.** Channels/providers may repeat similar logic (retries, media handling, message splitting). Keep each channel file self-contained — do not extract shared base classes just to dedupe.
- **Explicit over magical.** Config must be declared in `config/schema.py`; raise clear exceptions rather than silently correcting bad input.
- **Minimal change that solves the real problem.** No bundled refactors in a bugfix PR. Split clean-up into its own PR. Do not mix formatting/import-sort/quote churn into functional diffs.

## Security Boundaries (from `.agent/security.md`)

The agent has file/shell/web power. Do not bypass these guards:

- **Workspace restriction:** all filesystem tools resolve paths through the workspace path resolver (`agent/tools/filesystem.py` + `path_utils.py`) and enforce containment under the active workspace. Capability-specific roots: `extra_read_allowed_dirs` (read-only), `extra_write_allowed_dirs` (write), or exact file allowlists. `extra_allowed_dirs` is a legacy read-only alias. New path logic must go through the resolver.
- **SSRF protection:** every outbound HTTP request from a tool must pass `validate_url_target` (`security/network.py`) — blocks loopback, RFC1918, CGNAT, link-local, and cloud metadata (`169.254.169.254`). Escape hatch is `configure_ssrf_whitelist(cidrs)` from `config.tools.ssrf_whitelist`. Applies to HTTP/SSE MCP transports (validate URLs before probing; stdio MCP is exempt). **Never add direct `httpx.get`/`requests.get` in tools** — route through the web utilities or replicate the check.
- **Shell sandbox:** `tools/sandbox.py` wraps commands; only `bwrap` backend shipped (containerized Linux). Without `bwrap`, commands run in the native shell with workspace restriction as an *application-level* guard only (not process isolation).

## Common Gotchas (from `.agent/gotchas.md`)

- **Do not run `ruff format`** — destroys git blame. Use `ruff check` only. (CONTRIBUTING.md mentions it; ignore that.)
- **Windows is explicitly supported:** `ExecTool` defaults to PowerShell (`pwsh`, else Windows PowerShell); `cli/commands.py` forces UTF-8 stdio; MCP stdio commands normalize Windows paths. Always use `pathlib.Path`, never assume `/`.
- **Context pollution persists:** anything written to memory/session history/prompts can be replayed into future LLM calls. Sanitize timestamps, local media paths, tool-call echoes, and raw fallback dumps before they become model examples.
- **Atomic session writes** are mandatory for `history.jsonl` (see memory.py).

## Code Style

Python 3.11+, asyncio throughout, line length 100. Ruff rules `E, F, I, N, W` (E501 ignored). pytest with `asyncio_mode = "auto"`. Optional channel/provider deps are declared as `[project.optional-dependencies]` extras (e.g. `telegram`, `discord`, `azure`, `bedrock`) — match this pattern for new integrations.

## CI Constraints

PRs touching `.github/workflows/` must stay within GitHub Actions **free tier**: standard `ubuntu-latest`/`windows-latest` runners only — no macOS, no large/`*-cores`/`*-xlarge`/GPU/self-hosted runners, no large artifacts, no paid Marketplace actions. Call out any deviation in the PR description.

## Contribution Flow

Project lead **@re-bin** reviews and merges community PRs; **@chengyongru** reviews and may approve (merges are lead-only). For risky/larger changes, open an issue or draft PR early. See `CONTRIBUTING.md`.
