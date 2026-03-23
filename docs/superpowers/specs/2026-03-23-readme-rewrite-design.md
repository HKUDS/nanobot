# README Rewrite Design Spec

**Date:** 2026-03-23
**Topic:** README.md clean-slate rewrite
**Status:** Approved

---

## Goal

Replace the existing README.md with a fresh document that accurately describes the current state of the nanobot project. The old README contains stale content (outdated line counts, removed branch references, placeholder links, duplicate roadmap entries) and its structure does not reflect the project as it exists today.

## Audience

**Primary:** Developers who want to run nanobot as a self-hosted personal AI assistant — people evaluating it for use with their chat apps, configuring providers, and deploying it.

**Secondary:** Developers curious about the architecture (what modules exist, how it's structured) who want to extend or contribute — served by a brief architecture section, not deep internal docs.

## Value Proposition

**Self-hosted personal AI assistant.** Runs on your own machine, connects to your existing chat platforms (Telegram, Discord, Slack, WhatsApp, Email), and keeps your data local. Bring your own LLM via any major provider or a local model.

## What to Drop

- Line count claims ("~4,000 lines", "3,966 lines", "99% smaller than Clawdbot")
- News/changelog section (maintenance burden, goes stale)
- Reference to `feat/mem0-memory-integration` branch (merged, no longer relevant)
- `[PR](#)` placeholder link in news
- Duplicate "Multi-modal" roadmap entry
- "Agent Social Network" section (ClawHub/Moltbook/ClawdChat — niche, not core UX)

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

### 4. Quick Start
Goal: user is chatting with the agent in under 2 minutes.
1. `nanobot onboard`
2. Edit `~/.nanobot/config.json` — set API key + model (minimal example, OpenRouter)
3. `nanobot agent`

### 5. Chat Apps
Summary table (channel → what you need). Then one `<details>` block per channel with setup steps:
- Telegram (recommended)
- Discord
- Slack
- WhatsApp
- Email

### 6. Configuration
One `<details>` block per topic, all collapsed by default:

- **Agent Capabilities** — planning, verification mode, streaming, memory cap, shell mode, reranker rollout flags
- **Providers** — full table of all supported providers; nested `<details>` for: OpenAI Codex (OAuth), GitHub Copilot (OAuth), Custom (OpenAI-compatible), vLLM, Adding a New Provider (developer guide)
- **MCP (Model Context Protocol)** — stdio and HTTP transport config, toolTimeout
- **Multi-Agent Routing** — enable flag, classifier model, role definitions, built-in roles, field reference table
- **Security** — restrictToWorkspace, allowFrom, shell mode

### 7. Deployment
One `<details>` per deployment mode:
- Docker Compose
- Docker (standalone)
- Linux systemd user service

### 8. CLI Reference
Command table. Include: onboard, agent, gateway, status, provider login, channels login/status, replay-deadletters, cron add/list/remove.

Also: scheduled tasks (cron CLI) and heartbeat (HEARTBEAT.md) as collapsed `<details>`.

### 9. Architecture
Short paragraph (3-5 sentences): async bus-based routing, provider-agnostic LLM, plugin skill system, single-process design.

Project structure tree — accurate to current codebase, including:
- All current `agent/` modules (loop, turn_orchestrator, message_processor, streaming, verifier, consolidation, context, coordinator, delegation, tool_executor, registry, scratchpad, mission, capability, failure, tool_loop, observability, tracing, bus_progress, etc.)
- `agent/memory/` with full current file list
- `agent/tools/` with all current tools including powerpoint.py
- All top-level packages: channels, bus, providers, session, cron, heartbeat, skills, config, cli, errors.py, utils

### 10. Contribute
- Deduped roadmap checklist (remove duplicate Multi-modal entry)
- Contributors image
- Star history

---

## Accuracy Constraints

- Do not claim a specific line count anywhere
- Do not reference any git branch by name
- Do not include placeholder links
- The project structure tree must match actual files on disk at time of writing
- All config examples must use currently-valid field names (verify against `nanobot/config/schema.py`)

## Style Guidelines

- GitHub-flavored Markdown
- Prefer `<details>`/`<summary>` for all setup guides and advanced config — keeps the top of the page clean
- Code blocks for all JSON/bash examples
- No emoji outside the header and feature highlights (keep professional)
- Tip/Note callouts (`> [!TIP]`) used sparingly and only where genuinely useful
