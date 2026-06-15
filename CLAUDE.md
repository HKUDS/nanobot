# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Frank Deployment Patches

@FRANK.md

**After every upstream merge** (`git merge origin/main` or `git cherry-pick`): read `FRANK.md` and verify every patch is still in place before restarting Frank. Re-apply any that were overwritten. Update the status line in `FRANK.md` with the date.

---

## Design Constraints

- **Core stays small**: `agent/loop.py` and `agent/runner.py` are the critical path — changes there must be minimal and justified. New capabilities belong in `channels/`, `tools/`, skills, or MCP servers.
- **Provider wrappers**: `factory.py` automatically wraps providers with `FallbackProvider` (circuit-breaker failover) and `VisionAugmentedProvider` (image→text for text-only models). Do not duplicate this logic in individual providers — the wrapping happens once in `make_provider()`.
- **WebUI wire details** (`_turn_end`, `_goal_status`, title refreshes, goal-state sync) belong in `nanobot.session.webui_turns.WebuiTurnCoordinator`, not the agent loop.
- **No premature abstraction**: Channels and providers may repeat similar logic. Do not introduce shared base classes just to eliminate duplication — each file should be self-contained.
- **Explicit over magical**: All config must be declared in `config/schema.py` Pydantic models. Every provider resolution path must be traceable from `factory.py` to the concrete class.
- **Minimal PRs**: Bugfixes change only what is necessary. Refactors are separate PRs targeting `nightly`.

## Security Rules

- **Path handling**: Any new filesystem logic must use `_resolve_path` (`agent/tools/filesystem.py`), which enforces the workspace boundary (`allowed_dir` + media dir + `extra_allowed_dirs`).
- **SSRF**: All outbound HTTP from tools must pass through `validate_url_target` (`security/network.py`). Do not add bare `httpx.get` / `requests.get` calls in tools.
- **Sandbox backends**: To add a new shell sandbox, implement `_wrap_<name>(command, workspace, cwd) -> str` and register it in `_BACKENDS` (`tools/sandbox.py`).

## Gotchas

- **Do not run `ruff format`** — it destroys git blame history. Use `ruff check` only.
- **`${VAR}` in config**: Resolved at load time by `config/loader.py`. Missing env vars raise `ValueError` and fall back to default config — not a shell default-value syntax.
- **Windows support**: Use `pathlib.Path` everywhere; do not assume `/` separators. `ExecTool` uses `cmd /c` on Windows.
- **Prompt templates**: System prompts live in `nanobot/templates/` as Jinja2 markdown files (`identity.md`, `SOUL.md`, etc.) and are loaded by `utils/prompt_templates.py`. Treat changes there like runtime code changes.
- **Context pollution**: Anything written into memory or session history is replayed into future LLM calls. Sanitize metadata (timestamps, paths, tool-call echoes) before they become model examples.
- **Atomic session writes**: `agent/memory.py` writes `history.jsonl` via temp file + fsync + rename. Do not replace with a plain `open(..., "w")`.
- **Skills as extension point**: Agent "know-how" should be added as skills in `nanobot/skills/` (markdown + YAML frontmatter), not hardcoded into the agent loop.
- **Agent personas**: Context files for specific agent personas (product marketing, playbooks) live in `.agents/` and are loaded at runtime, not in `nanobot/templates/`.
- **Subconscious subsystem**: `nanobot/subconscious/` provides Obsidian vault integration (FTS search, knowledge graph, memory sync). Exposed to the agent via `agent/tools/subconscious.py`.
