# README Rewrite Design Spec

**Date:** 2026-03-23
**Topic:** README.md clean-slate rewrite
**Status:** Approved (v2 — post spec-review)

---

## Goal

Replace the existing README.md with a fresh document that accurately describes the current state of the nanobot project. The old README contains stale content (outdated line counts, removed branch references, placeholder links, duplicate roadmap entries, systemd docs for a deployment model the project has moved away from) and its structure does not reflect the project as it exists today.

## Audience

**Primary:** Developers who want to run nanobot as a self-hosted personal AI assistant — people evaluating it for use with their chat apps, configuring providers, and deploying it.

**Secondary:** Developers curious about the architecture (what modules exist, how it's structured) who want to extend or contribute — served by a brief architecture section, not deep internal docs.

## Value Proposition

**Self-hosted personal AI assistant.** Runs on your own machine, connects to your existing chat platforms (Telegram, Discord, Slack, WhatsApp, Email), and keeps your data local. Bring your own LLM via any major provider or a local model.

## What to Drop

- Line count claims ("~4,000 lines", "3,966 lines", "99% smaller than Clawdbot")
- News/changelog section (maintenance burden, goes stale)
- Branch name references (`feat/mem0-memory-integration`)
- Placeholder links (`[PR](#)`)
- Duplicate roadmap entries
- Agent Social Network section (ClawHub/Moltbook/ClawdChat — niche, not core UX)
- Linux systemd deployment guide (project has migrated away from systemd; only `deploy/migrate-from-systemd.sh` exists as a one-time migration helper)

---

## Section Structure

### 1. Header
- Logo image
- Badges: PyPI version, downloads, Python ≥3.10, MIT license, WeChat, Discord
- One-line pitch: "nanobot — self-hosted personal AI assistant"

### 2. What is nanobot
3-4 sentences describing what it is and what it does. No comparisons, no marketing superlatives. Cover: self-hosted, connects to chat apps, bring-your-own-LLM, persistent memory, tool use.

### 3. Install

Three options, shortest first:
- `uv tool install nanobot-ai` (recommended, fast)
- `pip install nanobot-ai` (stable)
- `git clone` + `pip install -e .` (latest/dev)

**Important:** PyPI package name is `nanobot-ai` (not `nanobot`). The CLI entry point is `nanobot`. This distinction must be explicit in the install instructions.

**User-facing extras to document** (in a separate subsection or note):
- `pip install nanobot-ai[oauth]` — enables OAuth login for OpenAI Codex and GitHub Copilot providers
- `pip install nanobot-ai[pptx]` — enables PowerPoint tools
- `pip install nanobot-ai[prometheus]` — enables Prometheus metrics export

Do not document `[dev]` — it is developer-only. Do NOT list a `[reranker]` extra — it does not exist in `pyproject.toml`. The reranker ships as part of the base package dependencies.

### 4. Quick Start

Goal: user is chatting with the agent in under 2 minutes.

1. `nanobot onboard`
2. Edit `~/.nanobot/config.json` — set API key + model. Minimal example using OpenRouter.
3. `nanobot agent -m "Hello!"` — single-shot test
4. Note: `nanobot agent` (no `-m`) enters interactive REPL mode. Exit with `Ctrl+D`, `exit`, or `/quit`.

### 5. Chat Apps

Summary table (channel → what you need). Then one `<details>` block per channel with numbered setup steps:
- Telegram (recommended)
- Discord
- Slack
- WhatsApp (requires Node.js ≥18)
- Email (IMAP/SMTP)

### 6. Configuration

One `<details>` block per topic, all collapsed by default:

**6a. Agent Capabilities**
Fields in `agents.defaults`: `planning_enabled`, `verification_mode`, `streaming`, `summary_model`, `memory_md_token_cap`, `shell_mode`.
Rollout environment variables: `NANOBOT_RERANKER_MODE`, `NANOBOT_RERANKER_ALPHA`, `NANOBOT_RERANKER_MODEL`.

**6b. Providers**
Full table of all supported providers (name → purpose → get API key link).
Nested `<details>` for: OpenAI Codex (OAuth), GitHub Copilot (OAuth), Custom (any OpenAI-compatible API), vLLM, Adding a New Provider (developer guide with ProviderSpec example).

**6c. MCP (Model Context Protocol)**
Stdio and HTTP transport config examples. `toolTimeout` override. Note that config format is compatible with Claude Desktop / Cursor.

**6d. Multi-Agent Routing**
Enable flag, classifier model, role definitions, built-in roles (code, research, writing, system, pm, general), per-role field reference table.

**6e. Feature Flags**
`FeaturesConfig` fields — master enable/disable switches. Document from `nanobot/config/schema.py:FeaturesConfig`. Fields use the `_enabled` suffix: `planning_enabled`, `verification_enabled`, `delegation_enabled`, `memory_enabled`, `skills_enabled`, `streaming_enabled`. Note the distinction: `verification_enabled` (in `FeaturesConfig`) is the master kill-switch, while `verification_mode` (in `AgentDefaults`) controls per-agent behavior (`on_uncertainty`/`always`/`off`).

**6f. Observability (Langfuse)**
`LangfuseConfig` fields: `enabled`, `host`, `public_key`, `secret_key`. Brief note on what gets traced (LLM calls, tool calls, agent turns).

**6g. Security**
`tools.restrictToWorkspace` — sandbox all file/shell tools to workspace. `channels.*.allowFrom` — user allowlist per channel. `shell_mode` (`denylist` vs `allowlist`).

### 7. Deployment

One `<details>` per deployment mode (no systemd):

- **Docker Compose** (local dev) — `docker compose run --rm nanobot-cli onboard`, then `docker compose up -d nanobot-gateway`
- **Docker** (standalone) — build, onboard, run gateway
- **Production** — brief note pointing to `deploy/deploy.sh` and `deploy/production/` for production Docker Compose setup; mention Caddy reverse proxy snippet at `deploy/caddy-snippet.conf`
- **Staging** — reference `deploy/staging/docker-compose.yml` and `deploy/staging/.env.example`

Note for former systemd users: `deploy/migrate-from-systemd.sh` handles one-time migration.

### 8. CLI Reference

**Main command table:**

| Command | Description |
|---|---|
| `nanobot onboard` | Initialize config & workspace |
| `nanobot agent` | Interactive chat (REPL) |
| `nanobot agent -m "..."` | Single-shot message |
| `nanobot gateway` | Start the gateway (all channels) |
| `nanobot ui` | Launch web UI |
| `nanobot status` | Show provider and channel status |
| `nanobot provider login <name>` | OAuth login (openai-codex, github-copilot) |
| `nanobot channels status` | Show channel connection status |
| `nanobot channels login` | Link WhatsApp (scan QR) |
| `nanobot replay-deadletters` | Replay failed messages from dead-letter queue |

**`<details>` — Scheduled Tasks (cron subgroup):**
`cron list`, `cron add --name ... --message ... --cron ...`, `cron add --every <seconds>`, `cron remove <id>`, `cron enable/disable <id>`, `cron run <id>`

**`<details>` — Heartbeat (Periodic Tasks):**
Not a CLI subgroup — configured via `HEARTBEAT.md` in the workspace. Gateway wakes every 30 minutes, reads the file, executes tasks, delivers results to the most recently active channel.

**`<details>` — Routing Diagnostics:**
`routing trace`, `routing metrics`, `routing dlq`, `routing replay` — for inspecting multi-agent routing decisions and replaying dead-letter queue entries.

**`<details>` — Memory Management:**
`memory inspect`, `memory metrics`, `memory rebuild`, `memory reindex`, `memory compact`, `memory verify`, `memory eval`, `memory conflicts`, `memory resolve`, `memory pin`, `memory unpin`, `memory outdated`

### 9. Architecture

Short paragraph (3-5 sentences): async bus-based message routing, provider-agnostic LLM integration via LiteLLM, plugin skill system, single-process design, no microservices.

Project structure tree — **must be accurate to current files on disk.** Key modules to include:

**`agent/` top-level:**
`loop.py`, `turn_orchestrator.py`, `message_processor.py`, `streaming.py`, `verifier.py`, `consolidation.py`, `context.py`, `coordinator.py`, `delegation.py`, `delegation_advisor.py`, `tool_executor.py`, `tool_loop.py`, `tool_setup.py`, `registry.py`, `capability.py`, `failure.py`, `mission.py`, `scratchpad.py`, `skills.py`, `observability.py`, `tracing.py`, `bus_progress.py`, `callbacks.py`, `metrics.py`, `prompt_loader.py`, `reaction.py`, `role_switching.py`

**`agent/memory/`:**
`store.py`, `event.py`, `extractor.py`, `ingester.py`, `retrieval.py`, `retriever.py`, `retrieval_planner.py`, `reranker.py`, `onnx_reranker.py`, `mem0_adapter.py`, `persistence.py`, `profile.py`, `consolidation_pipeline.py`, `context_assembler.py`, `snapshot.py`, `maintenance.py`, `graph.py`, `ontology.py`, `ontology_types.py`, `ontology_rules.py`, `entity_classifier.py`, `entity_linker.py`, `conflicts.py`, `helpers.py`, `rollout.py`, `constants.py`, `eval.py`

**`agent/tools/`:**
`base.py`, `registry.py`, `shell.py`, `filesystem.py`, `web.py`, `mcp.py`, `delegate.py`, `result_cache.py`, `email.py`, `excel.py`, `powerpoint.py`, `cron.py`, `feedback.py`, `message.py`, `mission.py`, `scratchpad.py`

**Top-level packages:** `channels/`, `bus/`, `providers/`, `session/`, `cron/`, `heartbeat/`, `skills/`, `config/`, `cli/`, `errors.py`, `utils/`

The tree should use brief one-line descriptions per file/package — not exhaustive internal documentation.

**Important:** Generate the project structure tree by running `find` on disk — do NOT copy from CLAUDE.md, which is known to be incomplete. The list of modules above in this spec is the canonical reference for what to include.

### 10. Contribute

- Deduped roadmap checklist (remove duplicate "Multi-modal" entry — keep only one)
- Contributors image (`contrib.rocks`)
- Star history chart

---

## Accuracy Constraints

- Do not claim a specific line count anywhere
- Do not reference any git branch by name
- Do not include placeholder links
- PyPI package name is `nanobot-ai`; CLI entry point is `nanobot`
- Project structure tree must match actual files on disk at time of writing
- All config field names must be verified against `nanobot/config/schema.py`
- Do not document the `deploy/migrate-from-systemd.sh` as a deployment method — reference it only as a migration helper

## Style Guidelines

- GitHub-flavored Markdown
- `<details>`/`<summary>` for all setup guides and advanced config — keeps the top of the page clean
- Code blocks for all JSON/bash examples
- No emoji outside the header and feature highlights
- Tip/Note callouts (`> [!TIP]`) used sparingly and only where genuinely useful
