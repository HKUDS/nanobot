# Project Manager Skill — Design Document

## Why This Skill Exists

### The Core Problem

AI agents are fundamentally stateless. Each conversation turn is a fresh inference with no persistent memory of prior work. This creates a critical gap for any project that spans multiple sessions:

1. **Context Window Limits**: Even with 128K+ token windows, conversation history gets truncated. Project decisions made 50 turns ago disappear.
2. **Memory Pollution**: When all project progress is stored in a single `MEMORY.md`, it grows to 1000+ lines. Retrieval becomes slow and noisy — finding "CMRA auth module status" requires scanning through unrelated project history.
3. **Lost Breakpoints**: Users say "continue last project" but the agent has no reliable way to know which project, what phase, or what the next step should be.
4. **Over-Engineering**: A simple task like "rename a variable" gets forced into a full 5-module project template, wasting tokens and cognitive overhead.

### Why Not Just Use the Built-in Memory Skill?

The official `memory` skill (and the upcoming Dream system) focuses on **automatic memory consolidation** — periodically summarizing conversation history into `MEMORY.md`. This is great for long-term user preferences and cross-project lessons, but it has fundamental limitations for project management:

| Dimension | Official Memory / Dream | Project Manager |
|-----------|------------------------|-----------------|
| **Granularity** | Global, monolithic | Per-project, isolated |
| **Trigger** | Automatic, periodic | Explicit, intent-driven |
| **Content** | User preferences, lessons learned | Project progress, todos, decisions |
| **Recovery** | Semantic search across all memory | Direct file read by project name |
| **Concurrency** | Single writer, potential conflicts | Read-merge-write per project |

**They are complementary, not competing.** Project progress goes in `STATUS.md`; user preferences go in `MEMORY.md`. The two never overlap.

## Architecture Decisions

### 1. Physical Isolation Over Logical Tags

**Decision**: Each project gets its own directory with a dedicated `STATUS.md`, rather than tagging entries in a shared file.

**Rationale**:
- File system provides natural isolation — no risk of Project A's progress overwriting Project B's
- `read_file` is O(1) — direct path access vs. scanning a 1000-line file
- Git diff is cleaner — changes are scoped to one project's file
- Concurrent sessions can operate on different projects without lock contention

### 2. Intent Recognition Over Rigid Keywords

**Decision**: Infer project operations from conversation context rather than requiring exact trigger phrases.

**Rationale**:
- Users naturally say "back to that CMRA thing" not "resume project cmra-geo"
- Fuzzy matching + index.md lookup handles imprecise references
- When ambiguous, show recent projects for selection instead of guessing

### 3. Tiered Templates Over One-Size-Fits-All

**Decision**: Two templates — Full (A) for complex projects, Lightweight (B) for simple tasks.

**Rationale**:
- Not every task deserves a 5-module STATUS.md
- Lightweight template reduces overhead for single-session tasks
- Auto-upgrade from B to A when complexity grows

### 4. Read-Merge-Write Over Blind Overwrite

**Decision**: Always read the latest `STATUS.md` before writing, then merge changes.

**Rationale**:
- Multiple agent instances (Feishu, WeChat, CLI) may operate on the same project
- Blind overwrite from stale cache causes data loss
- Read-merge-write is the simplest concurrent-safe pattern without locks

### 5. Index Self-Healing

**Decision**: Auto-create `index.md` on first use, auto-add missing projects.

**Rationale**:
- Users shouldn't need to manually maintain an index
- If a project directory exists but isn't in the index, it's a bug — fix it silently
- Index sorted by last active time surfaces relevant projects first

## Memory Boundary Rules

The most critical design constraint is **strict separation** between project progress and global memory:

```
workspace/
├── MEMORY.md                    ← User preferences, cross-project lessons ONLY
├── memory/
│   └── YYYY-MM-DD.md            ← One-line daily summary + STATUS.md reference
└── projects/
    ├── index.md                 ← Project registry
    ├── {project}/
    │   └── STATUS.md            ← Project progress, todos, decisions
    └── _archive/                ← Completed/abandoned projects
```

**Rules**:
1. Never store project progress in `MEMORY.md`
2. Daily logs contain only a summary + reference to `STATUS.md`
3. Cross-project lessons (e.g., "X approach caused Y pitfall") go in `MEMORY.md`
4. Project-specific decisions go in that project's `STATUS.md`

## Quantified Impact

| Metric | Before (Monolithic) | After (Project Manager) |
|--------|---------------------|------------------------|
| `MEMORY.md` size | 1153 lines | 167 lines (85% reduction) |
| Project recovery time | User re-describes context (~2 min) | Read `STATUS.md` (<1 sec) |
| Context pollution risk | High (all projects mixed) | Low (physical isolation) |
| Small task overhead | Full 5-module template | Lightweight 2-3 modules |
| Concurrent session safety | Single writer bottleneck | Per-project isolation |

## Future Extensions

1. **Git Integration**: Auto-record commit hashes in `STATUS.md` header for code-state correlation
2. **Auto-Archive**: Heartbeat task to detect inactive projects (>30 days) and prompt archival
3. **Cross-Project Dependencies**: Track when Project A blocks Project B
4. **Template Marketplace**: Community-contributed STATUS.md templates for specific domains (research, devops, design)

---

*v2.1 — Battle-tested across concurrent agent instances (Feishu, WeChat, CLI) with auto-healing index, concurrent-safe writes, and fuzzy-match fallback.*
