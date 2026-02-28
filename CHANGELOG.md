# Changelog

All notable changes to nanobot are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

- **Per-channel model routing** — each channel config (Telegram, Discord, WhatsApp, etc.) now
  accepts an optional `model` field. When set, that channel uses the specified model instead of
  the global `agents.defaults.model`. Useful for routing high-volume channels to a cheaper model
  while keeping interactive channels on a premium one.

- **Subagents now inherit MCP tools and cron scheduling** — `SubagentManager` now receives
  `mcp_servers` and `cron_service` from the parent `AgentLoop`. Subagents spawned via the
  `spawn` tool can use the same MCP-registered tools and schedule cron jobs, making them
  first-class citizens of the agent ecosystem.

- **Session cleanup CLI** — `nanobot sessions list` and `nanobot sessions cleanup --days N`
  commands for managing JSONL session files. Sessions older than N days (default 30) are
  removed. `--dry-run` shows what would be deleted without touching the filesystem.

- **GitHub Actions CI** (`.github/workflows/ci.yml`) — two-job pipeline:
  - Python: `ruff check`, `pytest`, `pip-audit`
  - Node.js: `npm audit --audit-level=high`, `npm run build`

- **CONTRIBUTING.md** — developer guide covering how to add channels, tools, providers, and
  skills, including the ABC interfaces and registry patterns.

- **bridge/README.md** — documents the Node.js WhatsApp bridge: WebSocket protocol, auth token
  negotiation, QR login, environment variables, and troubleshooting.

### Changed

- **Per-session concurrency** — the global `_processing_lock` that serialised every message from
  every channel has been replaced with per-session locks (`_session_locks`). Messages for
  different users/channels are now processed concurrently; only messages within the *same*
  session are still serialised (to prevent session corruption).

- **`_TOOL_RESULT_MAX_CHARS` raised from 500 → 5 000** — tool results stored in session JSONL
  files now retain up to 5 000 characters. This eliminates silent context loss between resumed
  sessions when tool output exceeded the old limit.

- **Sensitive arguments scrubbed from logs** — tool call arguments whose key contains
  `password`, `token`, `api_key`, `secret`, `auth`, `credential`, `private_key`, or
  `access_key` are replaced with `***` before being written to log files.

- **Workspace path in system prompt** — the agent's system prompt now shows `~/.nanobot/workspace`
  (home-relative) instead of the full absolute path, reducing username/path leakage.

- **MCP HTTP client now has a 30-second timeout** — previously `httpx.AsyncClient(timeout=None)`
  could hang the agent loop indefinitely on a slow or unresponsive MCP server.

- **Docker image runs as non-root** — a dedicated `nanobot` system user is created and the
  `USER nanobot` instruction added to the `Dockerfile`. The config directory is now at
  `/home/nanobot/.nanobot` inside the container. Update Docker volume mounts accordingly:
  ```
  -v ~/.nanobot:/home/nanobot/.nanobot
  ```

- **Gateway warns (or refuses) when running as root** — `nanobot gateway` now prints a prominent
  warning when `os.getuid() == 0` on Linux/macOS.

- **`allowFrom` open-access warning** — the gateway prints a `SECURITY WARNING` at startup for
  every enabled channel that has an empty `allowFrom` list, reminding operators to restrict
  access for production deployments.

- **WhatsApp bridge token passed via temp file** — the bridge authentication token is now
  written to a `0600` temporary file (`BRIDGE_TOKEN_FILE`) at startup instead of being passed
  as a plain environment variable, preventing exposure in `/proc/<pid>/environ` and `ps e`
  output.

### Fixed

- **Memory consolidation race condition** — background consolidation tasks now take a snapshot
  of `session.messages` *before* the first `await`, preventing a race with concurrent
  `_save_turn()` calls that could cause messages to be included in the consolidated summary
  non-deterministically.

### Documentation

- **README.md** — added "🧠 How It Works Internally" section with collapsible subsections on
  the Skills system, Session storage (JSONL format), Heartbeat (two-phase LLM decision),
  and the Memory system (MEMORY.md + HISTORY.md consolidation).
- **SECURITY.md** — updated to reflect all security improvements listed above; added guidance
  on the bridge token file, root-detection, log scrubbing, and MCP timeout.

---

## [0.1.4] — 2025-xx-xx

_Initial public release with 11 channel integrations, multi-provider LLM support, MCP tool
servers, cron scheduling, heartbeat service, and two-layer persistent memory._

---

[Unreleased]: https://github.com/HKUDS/nanobot/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/HKUDS/nanobot/releases/tag/v0.1.4
