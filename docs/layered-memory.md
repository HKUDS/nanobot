# Layered Memory

Layered Memory adds **structured memory** for agent sessions: short-term **Task Canvas** indexing for large tool results, plus a **long-term pipeline** (L0 → L1 → L2 → L3) inspired by [TencentDB Agent Memory](https://github.com/Tencent/TencentDB-Agent-Memory).

It complements — but does not fully replace — the existing memory stack in [Memory](./memory.md):

| Layer | What it is | When it helps |
|-------|------------|---------------|
| **Session replay** | Live `session.messages` in the prompt | Recent turns and tool calls |
| **Layered L0** | Sanitized dialogue in SQLite | Searchable conversation evidence |
| **Layered L1** | Atomic facts / rules (FTS) | Keyword recall, `memory_search` |
| **Layered L2** | Scenario Markdown files | Project/topic narratives |
| **Layered L3** | `USER.md` persona | Stable cross-session preferences |
| **Consolidator / Dream** | `history.jsonl` → `SOUL.md` / `MEMORY.md` | Batch consolidation over days |
| **Layered LM1** | `nodes.json` + `canvas.mmd` | Long tasks with many large tool results |

**Shipped in this branch:** LM1 (Task Canvas) + LM2 (L0/L1/capture/pipeline/recall/tools) + LM3 (L2 scenes, L3 persona).

---

## Architecture

```text
Turn内（短期）                    Turn外（长期 pipeline）
─────────────────                ─────────────────────────
Tool results → nodes / canvas    L0 capture → L1 extract → L2 scene → L3 USER.md
read_memory_node                 recall (turn 前) + memory_search / conversation_search
```

| Tier | Storage | Trigger | Recall |
|------|---------|---------|--------|
| **L0** | `{workspace}/.nanobot/memory.sqlite` | After each turn (`capture`) | `conversation_search` |
| **L1** | Same SQLite (`l1_memories` + FTS5) | Pipeline after N turns or idle | `memory_search`, recall prepend |
| **L2** | `{workspace}/memory/scenes/*.md` + `scene_index.json` | After L1 (delayed timer) | Scene navigation in recall; `read_file` for body |
| **L3** | `{workspace}/USER.md` | After L2 (serial, global) | `[User profile note]` in recall; bootstrap identity |
| **Canvas** | `.nanobot/canvas/{session}/` | Each tool / turn end | `[Task canvas]` runtime lines |

---

## Quick start

Layered Memory is **off by default**.

### LM1 only (Task Canvas)

```json
{
  "agents": {
    "defaults": {
      "layeredMemory": {
        "enable": true,
        "offload": { "enable": true }
      }
    }
  }
}
```

Requires `layeredMemory.enable` **and** `layeredMemory.offload.enable`.

### Full stack (L0–L3 + recall)

```json
{
  "agents": {
    "defaults": {
      "layeredMemory": {
        "enable": true,
        "offload": { "enable": true },
        "capture": { "enable": true },
        "recall": { "enable": true, "strategy": "fts" },
        "pipeline": {
          "everyNConversations": 1,
          "enableWarmup": false,
          "l2DelayAfterL1Seconds": 15
        },
        "persona": {
          "enable": true,
          "minIntervalSeconds": 30
        }
      }
    }
  }
}
```

Restart the gateway or CLI session after changing config. Run `pip install -e .` when testing a development checkout.

Subagents keep layered memory **disabled** by default (`layeredMemory.subagent.*`).

---

## LM1 — Task Canvas (short-term)

### On disk

```text
{workspace}/.nanobot/canvas/{safe_session_key}/
  nodes.json      # node index (metadata only)
  canvas.mmd      # Mermaid task graph (rule-generated)

{workspace}/.nanobot/tool-results/{session_bucket}/{tool_call_id}.txt
                  # full tool output (when output exceeds maxToolResultChars)
```

Session keys like `cli:direct` → directory `cli_direct`.

### Flow

```text
Tool executes → persist (if large) → register node → hook sync
Next turn → inject [Task canvas] → read_memory_node(node_id) for spilled bodies
```

### `read_memory_node`

Registered when `layeredMemory.offload.enable` is true.

| Argument | Default | Description |
|----------|---------|-------------|
| `node_id` | required | Tool call id from canvas or persist reference |
| `offset` | `1` | 1-based start line |
| `limit` | `2000` | Max lines |

Nodes with `path: null` only have a short summary; full text must still be in replay or re-fetched via tools.

See [Relationship to persist](#relationship-to-persist-and-context-budget) below for `maxToolResultChars` tuning.

---

## LM2 — L0 capture, L1 atoms, recall, search

### L0 — conversation store

After each turn, sanitized messages are appended to SQLite (`l0_messages`). Runtime blocks (`[Task canvas]`, recall injections) are stripped before storage.

- **Retention:** `capture.l0RetentionDays` (default `30`; `0` = no prune)
- **Not** a verbatim copy of session JSONL — see `sanitize` rules in code

### L1 — atomic memories

A background job reads recent L0 rows and calls the LLM to extract **atoms** (`preference`, `fact`, `event`, `rule`) into `l1_memories` with FTS5 indexing.

**Pipeline triggers:**

| Trigger | Config |
|---------|--------|
| Every N turns | `pipeline.everyNConversations` (warmup: 1→2→4→… when `enableWarmup: true`) |
| Idle timeout | `pipeline.l1IdleTimeoutSeconds` |

### Turn-before recall

When `recall.enable` is true, before each turn nanobot may inject runtime lines:

```text
[User profile note]
… excerpt from USER.md …

[Recalled memories]
- (rule) Only commit when user explicitly says commit

[Scene navigation]
- Layered Memory dev → memory/scenes/nanobot-layered-memory.md
(Use read_file to load a scene; navigation only.)

[Memory tools]
memory_search / conversation_search — ≤3 calls per turn combined
```

Capped by `recall.maxPrependChars` and `recall.timeoutMs`.

### Search tools

| Tool | Searches | When registered |
|------|----------|-----------------|
| `memory_search` | L1 FTS (or hybrid when embedding enabled) | `capture.enable` |
| `conversation_search` | L0 messages | `capture.enable` |

Budget: `recall.maxSearchCallsPerTurn` (default `3`) shared across both tools per turn.

---

## LM3 — L2 scenarios and L3 persona

### L2 — scenario blocks

After an L1 job completes, a **delayed timer** (`pipeline.l2DelayAfterL1Seconds`, default `90s`) may run an L2 job that synthesizes **scenario Markdown** from L1 atoms.

```text
{workspace}/memory/
  scene_index.json           # navigation index (title, path, summary)
  scenes/
    nanobot-layered-memory.md
    git-workflow.md
```

- **One file per ongoing topic** — related atoms merge into the same scene; new topics get new files
- **Recall injects navigation only** (title + path), not the full scene body
- **No TTL** — scenes persist until updated or manually deleted
- **Cold session:** if no activity for `pipeline.sessionActiveWindowHours`, pending L2 may be skipped

### L3 — user persona (`USER.md`)

After L2 succeeds, an L3 job (global serial queue) may rewrite **`{workspace}/USER.md`**:

- **Inputs:** current `USER.md`, scene index/bodies, recent L1 atoms
- **Output:** stable cross-session traits — language, communication style, standing rules, work context
- **Does not duplicate** per-project detail (that stays in L2 scenes) or transient task steps

**Safety:**

| Mechanism | Path / behavior |
|-----------|-----------------|
| File lock | `.nanobot/persona.lock` |
| Backup | `.nanobot/persona_backups/USER.{timestamp}.md` (`persona.backupCount`) |
| Min interval | `persona.minIntervalSeconds` between L3 runs |

### Pipeline timing (typical)

```text
Turn ends → L0 (immediate)
         → L1 (threshold or idle)
         → wait l2DelayAfterL1Seconds
         → L2 scene job
         → L3 USER.md job (if persona enabled + min interval elapsed)
Next turn → recall injects L1 + USER excerpt + scene navigation
```

For local testing, lower `l2DelayAfterL1Seconds` and `persona.minIntervalSeconds`.

---

## Layered Memory vs Dream

Both systems can touch long-term user knowledge. Defaults avoid double-writing `USER.md`.

| Aspect | Dream | Layered Memory |
|--------|-------|----------------|
| **Trigger** | Cron / `/dream` on `history.jsonl` batch | Per-turn capture + async pipeline |
| **Writes `MEMORY.md`** | Yes | No |
| **Writes `SOUL.md`** | Yes | No |
| **Writes `USER.md`** | Yes, **unless** `persona.enable` | **L3 only** when `persona.enable` |
| **Writes L0/L1** | No | Yes (`memory.sqlite`) |
| **Writes scenes** | No | Yes (`memory/scenes/`) |
| **Turn-before injection** | Via bootstrap / consolidator | `recall` runtime lines + tools |
| **Search** | Dream analysis, `/dream-log` | `memory_search`, `conversation_search` |
| **Tool-heavy session map** | No | Task Canvas (`read_memory_node`) |

When `layeredMemory.enable` and `layeredMemory.persona.enable` are both true (with `capture.enable`), Dream sets `skip_user_edits=True` and **does not edit `USER.md`** in Phase 2. Dream still maintains `MEMORY.md` and `SOUL.md`.

Disable `persona.enable` to let Dream own `USER.md` again.

See also: `.agent/gotchas.md` (Layered Memory vs Dream).

---

## Relationship to persist and Context Budget

### `maxToolResultChars`

When tool output exceeds `agents.defaults.maxToolResultChars` (default `16000`), nanobot spills to `.nanobot/tool-results/` and registers a node. Layered Memory reuses those files; `node_id` = `tool_call_id`.

### Context Budget (CB2)

Intended order: `filter (CB2) → persist → register node`. Canvas adds task structure; it does not replace filtering or consolidation.

### Runner microcompact

Old tool messages in replay may be replaced with placeholders. `read_memory_node` only recovers bodies that were **spilled** (`path` non-null).

---

## Configuration reference

All keys under `agents.defaults.layeredMemory` (camelCase in JSON). See [Configuration — Layered Memory](./configuration.md#layered-memory) for the full table.

### Master switch

| Key | Default | Description |
|-----|---------|-------------|
| `enable` | `false` | Master switch |

### Offload (LM1)

| Key | Default | Description |
|-----|---------|-------------|
| `offload.enable` | `false` | Canvas, nodes, `read_memory_node` |
| `offload.maxCanvasChars` | `1500` | Max `[Task canvas]` injection size |
| `offload.maxNodeSummaryChars` | `120` | Per-node summary in `nodes.json` |
| `offload.updateCanvasEveryNTools` | `0` | Refresh `canvas.mmd` every N tools; `0` = turn end |

### Capture (L0)

| Key | Default | Description |
|-----|---------|-------------|
| `capture.enable` | `false` | L0 write + pipeline + search tools |
| `capture.l0RetentionDays` | `30` | Prune L0 older than N days; `0` = keep |

### Pipeline (L1 → L2 → L3)

| Key | Default | Description |
|-----|---------|-------------|
| `pipeline.everyNConversations` | `5` | L1 trigger every N turns |
| `pipeline.enableWarmup` | `true` | 1→2→4→… until `everyN` |
| `pipeline.l1IdleTimeoutSeconds` | `600` | L1 on idle |
| `pipeline.l2DelayAfterL1Seconds` | `90` | Delay before L2 after L1 |
| `pipeline.l2MinIntervalSeconds` | `900` | Min gap between L2 runs per session |
| `pipeline.l2MaxIntervalSeconds` | `3600` | Max gap before L2 must run |
| `pipeline.sessionActiveWindowHours` | `24` | Skip L2 if session inactive |
| `pipeline.maxMemoriesPerSession` | `20` | L1 insert cap per session per job |
| `pipeline.enableL1Dedup` | `true` | Skip near-duplicate L1 atoms |
| `pipeline.extractionModel` | `null` | L1/L2/L3 LLM; `null` = main provider |

### Persona (L3)

| Key | Default | Description |
|-----|---------|-------------|
| `persona.enable` | `true` | L3 `USER.md` job; Dream skips USER when on |
| `persona.minIntervalSeconds` | `900` | Min gap between L3 runs |
| `persona.backupCount` | `3` | Rotating `USER.md` backups; `0` = none |
| `persona.maxUserChars` | `8000` | Max L3 `USER.md` size |
| `persona.lockTimeoutSeconds` | `30` | Persona file lock wait |
| `persona.model` | `null` | L3 LLM override |

### Recall

| Key | Default | Description |
|-----|---------|-------------|
| `recall.enable` | `false` | Turn-before L1 + USER + scene nav |
| `recall.strategy` | `hybrid` | `fts` / `embedding` / `hybrid` |
| `recall.topK` | `8` | Max L1 hits in recall |
| `recall.timeoutMs` | `5000` | Recall time budget |
| `recall.maxPrependChars` | `4000` | Max recall injection size |
| `recall.maxSearchCallsPerTurn` | `3` | `memory_search` + `conversation_search` budget |

### Subagent defaults

| Key | Default | Description |
|-----|---------|-------------|
| `subagent.enableOffload` | `false` | No canvas on subagents |
| `subagent.enableRecall` | `false` | No recall on subagents |
| `subagent.enableCapture` | `false` | No L0/pipeline on subagents |

---

## Inspecting on disk

```bash
# LM1 canvas
ls ~/.nanobot/workspace/.nanobot/canvas/cli_direct/
cat ~/.nanobot/workspace/.nanobot/canvas/cli_direct/nodes.json

# LM2 L0/L1
sqlite3 ~/.nanobot/workspace/.nanobot/memory.sqlite \
  "SELECT memory_type, content FROM l1_memories ORDER BY created_at DESC LIMIT 5;"

# LM3 L2 scenes
ls ~/.nanobot/workspace/memory/scenes/
cat ~/.nanobot/workspace/memory/scene_index.json

# LM3 L3 persona
cat ~/.nanobot/workspace/USER.md
ls ~/.nanobot/workspace/.nanobot/persona_backups/
```

---

## Tuning tips

| Goal | Suggestion |
|------|------------|
| Long repo exploration | `offload.enable: true`, `maxToolResultChars` 8k–16k |
| Faster L2/L3 while debugging | `everyNConversations: 1`, low `l2DelayAfterL1Seconds`, low `persona.minIntervalSeconds` |
| Lower LLM cost | `enableWarmup: true`, higher `l2MinIntervalSeconds`, higher `persona.minIntervalSeconds` |
| Tight prompt budget | Lower `maxCanvasChars`, `recall.maxPrependChars` |
| Dream owns USER again | `persona.enable: false` |

---

## Boundaries

| Component | Layered Memory | Classic memory |
|-----------|----------------|----------------|
| Writes | `memory.sqlite`, `memory/scenes/`, `USER.md` (L3), canvas | `sessions/`, `history.jsonl`, `MEMORY.md`, `SOUL.md` |
| Reads in prompt | Recall block, canvas, bootstrap `USER.md` | Session replay, consolidator, Dream files |
| Skills | Never writes `skills/` | Evolution / Dream (no skill create in Dream) |

---

## Further reading

- Design spec: `.agent/layered-memory/design.md`
- Implementation plan: `.agent/layered-memory/plan.md`
- Classic long-term memory: [Memory](./memory.md)
- All config keys: [Configuration](./configuration.md#layered-memory)
