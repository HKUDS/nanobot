# Upstream Sync Log

Tracks features brought in (or skipped) from [HKUDS/nanobot](https://github.com/HKUDS/nanobot).

---

## 2026-02-15 - Selective upstream sync

**Branch:** `upstream-sync-2026-02-15`
**Upstream HEAD:** `a5265c263d1ea277dc3197e63364105be0503d79`

### Features brought in

1. **CLI session_id default fix** — `"cli:default"` → `"cli:direct"` in `nanobot/cli/commands.py`
2. **History kvcache fix** — `last_consolidated: int = 0` field in `Session` dataclass
3. **asyncio.create_task fix** — SKIPPED (depended on unmerged memory consolidation at the time; superseded by PR #565)
4. **Consolidate offset tests** — `tests/test_consolidate_offset.py`
5. **max_messages increase** — `get_history()` default 50 → 500
6. **max_tokens/temperature wiring** — params added to `AgentLoop`, `SubagentManager`, wired to `provider.chat()`, added `SessionManager.invalidate()`
7. **Cron timezone fixes** — timezone-aware cron scheduling in `nanobot/cron/service.py`
8. **PR #565: Memory Redesign** — Two-layer `MemoryStore` (MEMORY.md + HISTORY.md), extracted `_run_agent_loop()`, `_consolidate_memory()`, `memory_window` config, `tools_used` tracking, new `nanobot/skills/memory/SKILL.md`
9. **PR #569: /new command** — Unified `/new` and `/help` slash commands in `AgentLoop._process_message()`, removed `session_manager` from channels, Telegram forwards commands via `_forward_command`
10. **PR #664: json_repair** — `json_repair.loads()` replaces `json.loads()` in memory consolidation and tool call argument parsing, added `json-repair>=0.30.0` dependency

### Intentionally skipped

- **PR #554: MCP support** — Not needed for this fork
- **Docs-only updates** — No functional changes

---

## 2026-02-15 - Pre-fork work reconciliation

**Upstream commit reviewed:** `c8831a1e1ee5557f318b52ad4ae9a8510432ca37` (2026-02-11)

These upstream PRs were independently implemented locally before formal sync tracking began:

### Already implemented locally
- PR #516: Fix Pydantic V2 deprecation warning - local PR #6
- PR #533: feat(cron): add 'at' parameter for one-time scheduled tasks - local commits `7c2ba0e`, `aebbfda`
- PR #538: Interleaved chain-of-thought - local commit `1378c7c`
- PR #543: Add edit_file tool and time context to sub agent - local commit `933e398`
- Commit `b429bf9`: Improve long-running stability for various channels - local commit `98dded4`
