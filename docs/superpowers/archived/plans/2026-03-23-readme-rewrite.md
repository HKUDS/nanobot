# README Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace README.md with a clean-slate document that accurately describes the current nanobot project for users who want to self-host it as a personal AI assistant.

**Architecture:** Single-file rewrite. The new README uses a layered structure: fast user-focused top (install, quick start, chat apps) with advanced topics in collapsed `<details>` sections. No code changes — documentation only.

**Tech Stack:** Markdown (GitHub-flavored), `<details>`/`<summary>` for collapsible sections.

**Spec:** `docs/superpowers/specs/2026-03-23-readme-rewrite-design.md`

---

## File Map

- **Modify:** `README.md` — complete rewrite (the only file changed in this plan)

---

### Task 1: Header + What Is Nanobot + Install

**Files:**
- Modify: `README.md`

**References to verify against:**
- `pyproject.toml` — package name (`nanobot-ai`), version, Python requirement, optional dependencies
- Existing badge URLs from current README lines 1-12

- [ ] **Step 1: Write header section**

Replace entire README content. Preserve existing badge URLs and logo. Drop the "Ultra-Lightweight" subtitle — use "Self-Hosted Personal AI Assistant" instead.

```html
<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: Self-Hosted Personal AI Assistant</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>
```

- [ ] **Step 2: Write "What is nanobot" section**

3-4 sentences. No marketing superlatives. Cover: self-hosted, chat apps, BYO-LLM, memory, tools.

```markdown
**nanobot** is a self-hosted personal AI assistant that connects to your chat platforms — Telegram, Discord, Slack, WhatsApp, and Email. Bring your own LLM from any major provider (OpenRouter, Anthropic, OpenAI, DeepSeek, Gemini, and more) or run a local model. The agent remembers conversations across sessions, uses tools (shell, filesystem, web search, email, spreadsheets, MCP), and can run scheduled tasks on its own.

<div align="center">
  <img src="nanobot_arch.png" alt="Architecture" width="800">
</div>
```

- [ ] **Step 3: Write Install section**

Three options. Explicitly note that the PyPI package is `nanobot-ai` while the CLI command is `nanobot`. Include optional extras (oauth, pptx, prometheus). Do NOT include `[reranker]` — it doesn't exist.

```markdown
## Install

```bash
# Recommended (fast)
uv tool install nanobot-ai

# Or via pip
pip install nanobot-ai

# Or from source (latest)
git clone https://github.com/HKUDS/nanobot.git && cd nanobot
pip install -e .
```

> [!TIP]
> The PyPI package is `nanobot-ai`. The CLI command is `nanobot`.

**Optional extras:**

| Extra | Install | What it enables |
|-------|---------|-----------------|
| `oauth` | `pip install nanobot-ai[oauth]` | OAuth login for OpenAI Codex and GitHub Copilot |
| `pptx` | `pip install nanobot-ai[pptx]` | PowerPoint file tools |
| `prometheus` | `pip install nanobot-ai[prometheus]` | Prometheus metrics export |
```

- [ ] **Step 4: Verify install section accuracy**

Run these checks:
```bash
grep 'name = "nanobot-ai"' pyproject.toml           # confirm package name
grep -A5 'optional-dependencies' pyproject.toml      # confirm extras are oauth, pptx, prometheus, dev
```

Expected: package name is `nanobot-ai`, extras match what we documented (no `reranker` extra).

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): rewrite header, intro, and install sections"
```

---

### Task 2: Quick Start

**Files:**
- Modify: `README.md` (append after Install section)

- [ ] **Step 1: Write Quick Start section**

Goal: running in 2 minutes. Use `nanobot agent -m "Hello!"` as the canonical first-run command (single-shot). Note interactive REPL mode.

```markdown
## Quick Start

**1. Initialize** config and workspace:

```bash
nanobot onboard
```

**2. Configure** — edit `~/.nanobot/config.json` and add your API key:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-..."
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-20250514"
    }
  }
}
```

**3. Chat:**

```bash
nanobot agent -m "Hello!"
```

For interactive mode (multi-turn conversation):

```bash
nanobot agent
```

Exit with `Ctrl+D`, `exit`, or `/quit`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): add quick start section"
```

---

### Task 3: Chat Apps

**Files:**
- Modify: `README.md` (append after Quick Start)

**References to verify:**
- Current README lines 162-377 (channel setup guides — reuse config JSON examples verbatim, they are accurate)

- [ ] **Step 1: Write Chat Apps section**

Summary table + one `<details>` per channel. Reuse the existing config JSON examples from the current README — they are correct and tested. Include all 5 channels: Telegram, Discord, WhatsApp, Slack, Email.

```markdown
## Chat Apps

Connect nanobot to your favorite chat platform.

| Channel | What you need |
|---------|---------------|
| **Telegram** | Bot token from @BotFather |
| **Discord** | Bot token + Message Content intent |
| **WhatsApp** | QR code scan (requires Node.js >=18) |
| **Slack** | Bot token + App-Level token |
| **Email** | IMAP/SMTP credentials |
```

Then add the 5 `<details>` blocks. Copy the Telegram, Discord, WhatsApp, Slack, and Email `<details>` sections from the current README (lines 172-377) — they contain accurate, tested config JSON and step-by-step instructions. No changes needed to the channel content itself.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): add chat apps section"
```

---

### Task 4: Configuration — Agent Capabilities + Providers

**Files:**
- Modify: `README.md` (append after Chat Apps)

**References to verify:**
- `nanobot/config/schema.py` — `AgentDefaults` class for field names/defaults
- `nanobot/config/providers_registry.py` — provider list

- [ ] **Step 1: Write Configuration header and Agent Capabilities**

All configuration sections use collapsed `<details>`. Start with Agent Capabilities. Remove the stale "`feat/mem0-memory-integration` branch" reference. Remove `pip install nanobot-ai[reranker]` mention (doesn't exist).

```markdown
## Configuration

All configuration lives in `~/.nanobot/config.json`.

<details>
<summary><b>Agent Capabilities</b></summary>

Configure agent behavior via `agents.defaults` in your config:

| Feature | Config Key | Default | Description |
|---------|-----------|---------|-------------|
| Planning | `planning_enabled` | `true` | Decomposes complex tasks into sub-steps before acting |
| Self-critique | `verification_mode` | `"on_uncertainty"` | Verifies tool outputs for correctness (`on_uncertainty`/`always`/`off`) |
| Summary compression | `summary_model` | `""` | LLM model for context window compression (empty = use main model) |
| Memory cap | `memory_md_token_cap` | `1500` | Max tokens injected from MEMORY.md into system prompt |
| Shell mode | `shell_mode` | `"denylist"` | Shell command security (`denylist` blocks destructive commands, `allowlist` for strict allowlisting) |

> Note: `streaming` is not an `AgentDefaults` field. Streaming is controlled by `features.streaming_enabled` (see Feature Flags section).

**Rollout flags** (environment variables):

| Variable | Values | Description |
|----------|--------|-------------|
| `NANOBOT_RERANKER_MODE` | `disabled`/`shadow`/`enabled` | Cross-encoder re-ranker for memory retrieval |
| `NANOBOT_RERANKER_ALPHA` | `0.0`-`1.0` | Blend weight (1.0 = pure cross-encoder, 0.0 = pure heuristic) |
| `NANOBOT_RERANKER_MODEL` | model name | Override re-ranker model (default: `ms-marco-MiniLM-L-6-v2`) |

</details>
```

- [ ] **Step 2: Write Providers section**

Reuse the existing provider table from the current README (lines 467-485) — it is accurate and complete. Wrap the whole thing in `<details>`. Include nested `<details>` for OpenAI Codex, Custom Provider, vLLM, and Adding a New Provider (copy from current README lines 487-621).

```markdown
<details>
<summary><b>Providers</b></summary>

> [!TIP]
> - **Groq** provides free voice transcription via Whisper. Telegram voice messages are automatically transcribed.
> - **Zhipu Coding Plan**: Set `"apiBase": "https://open.bigmodel.cn/api/coding/paas/v4"` in your zhipu provider config.
> - **MiniMax (Mainland China)**: Set `"apiBase": "https://api.minimaxi.com/v1"` in your minimax provider config.
> - **VolcEngine Coding Plan**: Set `"apiBase": "https://ark.cn-beijing.volces.com/api/coding/v3"` in your volcengine provider config.

| Provider | Purpose | Get API Key |
|----------|---------|-------------|
| `custom` | Any OpenAI-compatible endpoint (direct, no LiteLLM) | - |
| `openrouter` | LLM (recommended, access to all models) | [openrouter.ai](https://openrouter.ai) |
| ... (full table from current README) |
| `github_copilot` | LLM (GitHub Copilot, OAuth) | `nanobot provider login github-copilot` |

<!-- Then the 4 nested <details>: OpenAI Codex, Custom Provider, vLLM, Adding a New Provider -->
<!-- Copy verbatim from current README lines 487-621 -->

</details>
```

- [ ] **Step 3: Verify provider table against registry**

```bash
grep 'name="' nanobot/config/providers_registry.py | grep -oP 'name="\K[^"]+' | sort
```

Confirm all providers in the table match the registry.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): add agent capabilities and providers config"
```

---

### Task 5: Configuration — MCP, Multi-Agent, Feature Flags, Observability, Security

**Files:**
- Modify: `README.md` (append after Providers `</details>`)

**References to verify:**
- `nanobot/config/schema.py` — `FeaturesConfig`, `LangfuseConfig`, `ToolsConfig`, `MCPServerConfig`
- Current README lines 624-688 (MCP + Security — reusable)
- Current README lines 417-457 (Multi-Agent Routing — reusable)

- [ ] **Step 1: Write MCP section**

Copy the MCP section from current README (lines 624-674) — it is accurate. Wrap in `<details>`.

- [ ] **Step 2: Write Multi-Agent Routing section**

Copy from current README (lines 417-457) — it is accurate. Wrap in `<details>`.

- [ ] **Step 3: Write Feature Flags section**

New section — doesn't exist in current README. Source from `nanobot/config/schema.py:FeaturesConfig`.

```markdown
<details>
<summary><b>Feature Flags</b></summary>

Master switches in the `features` config block. These override per-agent settings.

| Flag | Default | What it controls |
|------|---------|-----------------|
| `planning_enabled` | `true` | Task decomposition and planning |
| `verification_enabled` | `true` | Answer verification (master switch — distinct from `verification_mode` in agent defaults) |
| `delegation_enabled` | `true` | Multi-agent delegation |
| `memory_enabled` | `true` | Persistent memory |
| `skills_enabled` | `true` | Skill discovery and loading |
| `streaming_enabled` | `true` | Streaming LLM responses |

```json
{
  "features": {
    "planning_enabled": false,
    "delegation_enabled": false
  }
}
```

</details>
```

- [ ] **Step 4: Write Observability section**

New section. Source from `nanobot/config/schema.py:LangfuseConfig`.

```markdown
<details>
<summary><b>Observability (Langfuse)</b></summary>

nanobot traces LLM calls, tool invocations, and agent turns to [Langfuse](https://langfuse.com/).

The config uses camelCase in JSON (generated by Pydantic's `alias_generator=to_camel`). Use camelCase consistently in the example and table.

```json
{
  "langfuse": {
    "enabled": true,
    "publicKey": "pk-...",
    "secretKey": "sk-...",
    "host": "https://cloud.langfuse.com"
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Enable/disable tracing |
| `publicKey` | `""` | Langfuse public key |
| `secretKey` | `""` | Langfuse secret key |
| `host` | `"https://cloud.langfuse.com"` | Langfuse server URL (self-hosted or cloud) |
| `environment` | `"development"` | Environment tag |
| `sampleRate` | `1.0` | Fraction of traces to send (0.0-1.0) |

</details>
```

- [ ] **Step 5: Write Security section**

Copy from current README (lines 679-688). Wrap in `<details>`.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs(readme): add MCP, routing, feature flags, observability, security config"
```

---

### Task 6: Deployment

**Files:**
- Modify: `README.md` (append after Configuration)

**References to verify:**
- `docker-compose.yml` — service names, ports
- `deploy/staging/docker-compose.yml` — staging config
- `deploy/production/docker-compose.yml` — production config
- `deploy/deploy.sh` — deployment script flags

- [ ] **Step 1: Write Deployment section**

Three `<details>` blocks: Docker Compose (local dev), Docker (standalone), Production/Staging. No systemd. Add a brief note for former systemd users referencing `deploy/migrate-from-systemd.sh`.

Copy Docker Compose and Docker content from current README (lines 745-782) — they are accurate. Add new Production/Staging `<details>`:

```markdown
## Deployment

<details>
<summary><b>Docker Compose</b></summary>

<!-- Copy from current README lines 750-762 -->

</details>

<details>
<summary><b>Docker</b></summary>

<!-- Copy from current README lines 764-782 -->

</details>

<details>
<summary><b>Production & Staging</b></summary>

Use the deployment script for production and staging environments:

```bash
# Deploy to production
bash deploy/deploy.sh --env production

# Deploy to staging
bash deploy/deploy.sh --env staging

# Rollback
bash deploy/deploy.sh --env production --rollback
```

Configuration files:
- Production: `deploy/production/docker-compose.yml` + `deploy/production/.env.example`
- Staging: `deploy/staging/docker-compose.yml` + `deploy/staging/.env.example`
- Caddy reverse proxy: `deploy/caddy-snippet.conf`

> Former systemd users: run `deploy/migrate-from-systemd.sh` to migrate to Docker Compose.

</details>
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): add deployment section"
```

---

### Task 7: CLI Reference

**Files:**
- Modify: `README.md` (append after Deployment)

**References to verify:**
- `nanobot/cli/commands.py` — exact command names and subgroups

- [ ] **Step 1: Write CLI Reference section**

Main command table + 4 collapsed `<details>` blocks for subgroups (cron, heartbeat, routing, memory).

```markdown
## CLI Reference

| Command | Description |
|---------|-------------|
| `nanobot onboard` | Initialize config and workspace |
| `nanobot agent` | Interactive chat (REPL) |
| `nanobot agent -m "..."` | Single-shot message |
| `nanobot gateway` | Start the gateway (all channels) |
| `nanobot ui` | Launch web UI |
| `nanobot status` | Show provider and channel status |
| `nanobot provider login <name>` | OAuth login (openai-codex, github-copilot) |
| `nanobot channels status` | Show channel connection status |
| `nanobot channels login` | Link WhatsApp (scan QR) |
| `nanobot replay-deadletters` | Replay failed messages from dead-letter queue |

Interactive mode exits: `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.
```

Then add 4 `<details>` blocks:

**Scheduled Tasks (cron):** Copy from current README (lines 708-723), add `cron enable`, `cron run` commands.

**Heartbeat:** Copy from current README (lines 725-743). Clarify it's config-driven via `HEARTBEAT.md`, not a CLI subgroup.

**Routing Diagnostics:** New section.
```markdown
<details>
<summary><b>Routing Diagnostics</b></summary>

```bash
nanobot routing trace         # Show recent routing decisions
nanobot routing metrics       # Show routing metrics/stats
nanobot routing dlq           # Show dead-letter queue
nanobot routing replay        # Replay from dead-letter queue
```

</details>
```

**Memory Management:** New section.
```markdown
<details>
<summary><b>Memory Management</b></summary>

```bash
nanobot memory inspect        # Inspect memory state
nanobot memory metrics        # Show memory metrics
nanobot memory rebuild        # Rebuild memory store
nanobot memory reindex        # Reindex vector store
nanobot memory compact        # Compact memory
nanobot memory verify         # Verify memory integrity
nanobot memory eval           # Run memory evaluation
nanobot memory conflicts      # Show memory conflicts
nanobot memory resolve        # Resolve memory conflicts
nanobot memory pin            # Pin a memory (prevent deletion)
nanobot memory unpin          # Unpin a memory
nanobot memory outdated       # Show outdated memories
```

</details>
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): add CLI reference section"
```

---

### Task 8: Architecture + Project Structure

**Files:**
- Modify: `README.md` (append after CLI Reference)

**References to verify:**
- Run `find nanobot/agent -name '*.py' | sort` to get accurate file list
- Run `find nanobot/agent/memory -name '*.py' | sort` for memory subpackage
- Run `find nanobot/agent/tools -name '*.py' | sort` for tools subpackage

- [ ] **Step 1: Write Architecture section**

Short paragraph (3-5 sentences) + accurate project structure tree. Generate tree from disk, NOT from CLAUDE.md. Include one-line descriptions per file.

```markdown
## Architecture

nanobot uses an async bus-based message routing architecture. Chat channels push messages onto a central bus; the agent engine consumes them, calls LLMs via a provider-agnostic layer (LiteLLM), and routes responses back. A plugin skill system and MCP support extend agent capabilities. Single-process design — no microservices.

```
nanobot/
├── agent/                    # Core agent engine
│   ├── loop.py               # Plan-Act-Observe-Reflect main loop
│   ├── turn_orchestrator.py  # Turn lifecycle orchestration
│   ├── message_processor.py  # Message processing pipeline
│   ├── streaming.py          # Streaming LLM calls
│   ├── verifier.py           # Answer verification
│   ├── consolidation.py      # Memory consolidation orchestration
│   ├── context.py            # Prompt assembly + token budgeting
│   ├── coordinator.py        # Multi-agent intent routing
│   ├── delegation.py         # Delegation routing + cycle detection
│   ├── delegation_advisor.py # Delegation decision advisor
│   ├── tool_executor.py      # Tool batching (parallel/sequential)
│   ├── tool_loop.py          # Think-act-observe loop
│   ├── tool_setup.py         # Tool initialization
│   ├── registry.py           # Agent role registry
│   ├── capability.py         # Unified capability registry
│   ├── failure.py            # Failure classification + loop detection
│   ├── mission.py            # Background mission manager
│   ├── scratchpad.py         # Session-scoped artifact sharing
│   ├── skills.py             # Skill discovery + loading
│   ├── observability.py      # Langfuse OTEL tracing
│   ├── tracing.py            # Correlation IDs + structured logging
│   ├── bus_progress.py       # Bus progress reporting
│   ├── callbacks.py          # Agent callbacks
│   ├── metrics.py            # Agent metrics
│   ├── prompt_loader.py      # Prompt template loading
│   ├── reaction.py           # Reaction handling
│   ├── role_switching.py     # Role switching logic
│   ├── memory/               # Persistent memory subsystem
│   │   ├── store.py          # MemoryStore — primary API
│   │   ├── event.py          # MemoryEvent model
│   │   ├── extractor.py      # LLM + heuristic event extraction
│   │   ├── ingester.py       # Memory ingestion pipeline
│   │   ├── retriever.py      # Memory retrieval engine
│   │   ├── retrieval.py      # Local keyword search fallback
│   │   ├── retrieval_planner.py # Retrieval strategy planning
│   │   ├── reranker.py       # Cross-encoder re-ranking
│   │   ├── onnx_reranker.py  # ONNX Runtime re-ranker
│   │   ├── mem0_adapter.py   # mem0 vector store adapter
│   │   ├── persistence.py    # File I/O (events.jsonl, MEMORY.md)
│   │   ├── profile_io.py     # Profile file I/O
│   │   ├── profile_correction.py # Profile correction logic
│   │   ├── consolidation_pipeline.py # Consolidation pipeline
│   │   ├── context_assembler.py # Memory context assembly
│   │   ├── snapshot.py       # Memory snapshots
│   │   ├── maintenance.py    # Memory maintenance tasks
│   │   ├── graph.py          # Knowledge graph (networkx)
│   │   ├── ontology.py       # Ontology management
│   │   ├── ontology_types.py # Ontology type definitions
│   │   ├── ontology_rules.py # Ontology rules
│   │   ├── entity_classifier.py # Entity type classification
│   │   ├── entity_linker.py  # Entity linking + resolution
│   │   ├── conflicts.py      # Memory conflict detection
│   │   ├── helpers.py        # Memory helpers
│   │   ├── rollout.py        # Feature rollout gates
│   │   ├── token_budget.py   # Token budget management
│   │   ├── constants.py      # Constants + tool schemas
│   │   └── eval.py           # Memory evaluation
│   └── tools/                # Built-in tools
│       ├── base.py           # Tool ABC + ToolResult
│       ├── registry.py       # Tool registry
│       ├── shell.py          # Shell execution (deny/allow)
│       ├── filesystem.py     # File read/write/edit/list
│       ├── web.py            # WebFetch + WebSearch
│       ├── mcp.py            # Model Context Protocol
│       ├── delegate.py       # Multi-agent delegation
│       ├── result_cache.py   # Result caching + summarization
│       ├── email.py          # Email checking
│       ├── excel.py          # Spreadsheet tools
│       ├── powerpoint.py     # PowerPoint tools
│       ├── cron.py           # Scheduled task tools
│       ├── feedback.py       # User feedback
│       ├── message.py        # Outbound messaging
│       ├── mission.py        # Background mission tools
│       └── scratchpad.py     # Scratchpad read/write
├── channels/                 # Chat platforms
├── bus/                      # Async message bus
├── providers/                # LLM providers
├── session/                  # Conversation sessions
├── cron/                     # Scheduled task service
├── heartbeat/                # Periodic task execution
├── skills/                   # Built-in skills
├── config/                   # Pydantic config + loader
├── cli/                      # Typer CLI
├── errors.py                 # Error taxonomy
└── utils/                    # Helpers
```
```

- [ ] **Step 2: Verify project structure tree against disk**

Run these commands and confirm every file listed in the tree actually exists:

```bash
find nanobot/agent -maxdepth 1 -name '*.py' ! -name '__init__.py' | sort
find nanobot/agent/memory -name '*.py' ! -name '__init__.py' | sort
find nanobot/agent/tools -name '*.py' ! -name '__init__.py' | sort
```

If any files exist on disk but are NOT in the tree, add them. If any files are in the tree but NOT on disk, remove them.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): add architecture and project structure"
```

---

### Task 9: Contribute + Star History + Footer

**Files:**
- Modify: `README.md` (append after Architecture)

- [ ] **Step 1: Write Contribute section**

Deduped roadmap (remove duplicate Multi-modal entry). Keep checked items. Preserve contributor image and star history from current README.

```markdown
## Contribute

PRs welcome!

**Roadmap** — pick an item and [open a PR](https://github.com/HKUDS/nanobot/pulls):

- [x] **Long-term memory** — mem0-backed persistent memory with hybrid retrieval
- [x] **Better reasoning** — Multi-step planning, task decomposition, and self-critique
- [x] **Self-improvement** — Learn from feedback (emoji reactions + explicit feedback tool)
- [ ] **Multi-modal** — See and hear (images, voice, video)
- [ ] **More integrations** — Calendar and more

### Contributors

<a href="https://github.com/HKUDS/nanobot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/nanobot&max=100&columns=12&updated=20260210" alt="Contributors" />
</a>

## Star History

<div align="center">
  <a href="https://star-history.com/#HKUDS/nanobot&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date" style="border-radius: 15px; box-shadow: 0 0 30px rgba(0, 217, 255, 0.3);" />
    </picture>
  </a>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): add contribute section, roadmap, and star history"
```

---

### Task 10: Final Verification

**Files:**
- Verify: `README.md`

- [ ] **Step 1: Check for dropped content**

Verify these items from the spec's "What to Drop" list are NOT in the new README:
```bash
grep -i "4,000\|3,966\|ultra-lightweight\|99% smaller\|Clawdbot" README.md   # should return nothing
grep "feat/mem0\|feat/memory" README.md                                       # should return nothing
grep '\[PR\](#)' README.md                                                    # should return nothing
grep -i "systemd\|\.service" README.md                                        # only migration note, not setup guide
grep -i "ClawHub\|Moltbook\|ClawdChat\|Social Network" README.md             # should return nothing
```

All greps should return empty (except the systemd migration note).

- [ ] **Step 2: Check for accuracy issues**

```bash
grep 'nanobot-ai\[reranker\]' README.md          # should return nothing (extra doesn't exist)
grep 'feat/' README.md                             # should return nothing (no branch refs)
grep '\](#)' README.md                             # should return nothing (no placeholder links)
```

- [ ] **Step 3: Run linting**

```bash
make lint && make typecheck
```

Should pass (no code changed, but confirms no accidental file corruption).

- [ ] **Step 4: Final commit (if any fixes needed)**

```bash
git add README.md
git commit -m "docs(readme): final verification fixes"
```
