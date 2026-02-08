# mentat-memory

**Fractal memory system for AI agents with long-term continuity**

---

## Overview

mentat-memory is a complete memory architecture for AI agents that provides:
- **Fractal diary structure** (daily → weekly → monthly → annual)
- **Semantic search** for intelligent context loading
- **Session summarization** with subagent processing
- **Overnight analysis** (Sandman system) for autonomous reflection
- **Sticky-notes** for timeless reference knowledge

This is NOT a simple key-value store. It's a living memory system that mirrors how humans consolidate information over time.

---

## Core Concepts

### Fractal Diary Hierarchy
```
Daily logs (raw)
  ↓ rollup
Weekly summaries (distilled patterns)
  ↓ rollup
Monthly trajectories (progress tracking)
  ↓ rollup
Annual themes (year-level milestones)
  ↓ curate
MEMORY.md (core long-term memory)
```

Each level compresses and consolidates the level below it, keeping what matters and discarding noise.

### Information Flow
```
Conversation → daily diary → weekly → monthly → annual → MEMORY.md
                ↓
           sticky-notes (timeless facts)
```

---

## Directory Structure

```
memory/
├── MEMORY.md                    # Core long-term memory (main session only)
├── diary/
│   └── YYYY/
│       ├── daily/YYYY-MM-DD.md      # Raw session logs
│       ├── weekly/YYYY-Wnn.md       # Weekly summaries
│       ├── monthly/YYYY-MM.md       # Monthly trajectories
│       ├── annual.md                # Year-level themes
│       └── .state.json              # Session tracking state
└── sticky-notes/
    ├── health/                  # Training, biometrics, patterns
    ├── projects/                # Active work, decisions
    ├── tech/                    # Code snippets, commands
    └── survival/                # Emergency contacts, quick wins

scripts/
├── load-context.py              # Chronological context loader
├── load-context-semantic.py     # Semantic search loader
├── search-unsummarized.py       # Search recent session transcripts
├── rollup-daily.py              # Daily → weekly consolidation
├── rollup-weekly.py             # Weekly → monthly consolidation
├── rollup-monthly.py            # Monthly → annual consolidation
├── summarize-session-direct.py  # Session → diary entry
├── build-memory-index.py        # Build vector search index
├── sandman-nanobot.py           # Overnight analysis orchestrator
└── verify-startup.py            # Verify startup compliance
```

---

## Key Scripts

### Context Loading

**`load-context.py`** - Chronological diary loading
```bash
# Load today → this week → this month → this year
python3 scripts/load-context.py

# Check for unsummarized sessions first
python3 scripts/load-context.py --check-sessions
```

**`load-context-semantic.py`** - Query-driven semantic search
```bash
# Find relevant memories by topic
python3 scripts/load-context-semantic.py "recent work and active projects"

# Search with specific question
python3 scripts/load-context-semantic.py "what was the secret word?"

# Options: --top-k N, --min-score X, --json
```

**`search-unsummarized.py`** - Search raw session transcripts
```bash
# Search last 24hrs of sessions (not yet in diary)
python3 scripts/search-unsummarized.py "secret word"

# Solves "secret word problem" for very recent context
```

### Memory Consolidation

**`rollup-daily.py`** - Daily → weekly summaries
```bash
# Summarize today's sessions into this week's file
python3 scripts/rollup-daily.py
```

**`rollup-weekly.py`** - Weekly → monthly summaries
```bash
# Consolidate this week into this month
python3 scripts/rollup-weekly.py
```

**`rollup-monthly.py`** - Monthly → annual summaries
```bash
# Consolidate this month into annual file
python3 scripts/rollup-monthly.py
```

### Session Processing

**`summarize-session-direct.py`** - Convert session transcript to diary entry
```bash
# Summarize specific session
python3 scripts/summarize-session-direct.py <session_id>

# Output includes user messages, assistant messages, tools used
```

### Vector Search

**`build-memory-index.py`** - Build ChromaDB vector index
```bash
# Index all diary entries and sticky-notes
python3 scripts/build-memory-index.py

# Rebuild after major memory updates
```

### Verification

**`verify-startup.py`** - Check startup sequence compliance
```bash
# Verify all required steps completed
python3 scripts/verify-startup.py

# Exit code 0 = pass, 1 = fail
```

---

## Startup Sequence (for Agents)

**CRITICAL:** This must run BEFORE your first reply in each session.

### Step 1: Load Context
```bash
# Option A: Semantic (recommended)
python3 scripts/load-context-semantic.py "recent work and active projects"
python3 scripts/search-unsummarized.py "recent work and active projects"

# Option B: Chronological (fallback)
python3 scripts/load-context.py
```

### Step 2: Check for Unsummarized Sessions
```bash
python3 scripts/load-context.py --check-sessions
```

If output contains `SUMMARIZE_PENDING`, spawn subagents to process them:

```python
# For each pending session:
#   Label: Summarize Session <session_id[:8]> (<date>)
#   Task: Run summarize-session-direct.py, write diary entry, update .state.json
```

### Step 3: Read Core Files
1. `SOUL.md` - who you are
2. `USER.md` - who you're helping
3. Diary context (from Step 1)
4. `MEMORY.md` (main session only, NOT group chats)

### Step 4: Verify Compliance
```bash
python3 scripts/verify-startup.py
```

If this fails, go back and complete missing steps. **Do not greet** until verification passes.

See `AGENTS.md` in workspace root for full startup documentation.

---

## Sandman Overnight Analysis

**Purpose:** Autonomous overnight processing of the day's sessions

**How it works:**
1. Cron job triggers at 3:00 AM MST
2. Spawns 6 parallel subagents analyzing different aspects:
   - Enforcement (startup compliance)
   - Patterns (conversation dynamics)
   - Consistency (memory accuracy)
   - Projects (active work tracking)
   - Self-analysis (meta-reflection)
   - Optimization (system improvements)
3. Each subagent writes findings to `memory/sandman/YYYY-MM-DD-<task>.md`
4. Morning summary generated at 6:00 AM

**Budget:** $5/night dedicated spending

**Setup:**
```bash
# Install cron job
python3 scripts/sandman-nanobot.py --install-cron

# Manual run (testing)
python3 scripts/sandman-nanobot.py
```

See `scripts/README-sandman.md` for full documentation.

---

## Memory Maintenance

### Automated (via cron)
- **Daily (23:59):** `rollup-daily.py` - today → this week
- **Weekly (Sun 23:59):** `rollup-weekly.py` - week → this month
- **Monthly (EOM):** `rollup-monthly.py` - month → annual
- **Overnight (3:00 AM):** Sandman analysis

### Manual (periodic)
- Review recent diary entries for patterns
- Extract timeless facts → sticky-notes
- Update MEMORY.md if major milestones occurred
- Rebuild vector index after major memory updates

---

## Privacy & Security

**NEVER commit personal memory files:**
- `memory/MEMORY.md`
- `memory/diary/`
- `memory/sticky-notes/`
- `USER.md`, `TOOLS.md`, `HEARTBEAT.md`
- Session transcripts

**Safe to commit:**
- Scripts (`scripts/*.py`)
- Documentation (`scripts/README-*.md`)
- Template files
- This SKILL.md

Use the provided `.gitignore` to protect sensitive files.

---

## Dependencies

### Required
- Python 3.x
- Access to LLM API (for summarization)

### Optional (for semantic search)
- Ollama with `qwen3-embedding` model
- ChromaDB (`pip install chromadb`)
- Vector index at `~/.memory-vectors/`

### Optional (for Sandman)
- Cron access (for scheduled runs)
- Subagent spawning capability

---

## Integration Examples

### Nanobot
```python
# In startup sequence (AGENTS.md):
exec("python3 scripts/load-context-semantic.py 'recent work'")
exec("python3 scripts/search-unsummarized.py 'recent work'")
exec("python3 scripts/verify-startup.py")
```

### OpenClaw
```python
# Similar pattern, adjust for OpenClaw's tool interface
```

### Custom Platforms
1. Implement subagent spawning (or skip Sandman)
2. Adapt session transcript access for `summarize-session-direct.py`
3. Update paths in scripts if workspace location differs
4. Test startup sequence with `verify-startup.py`

---

## Troubleshooting

### "Verification failed" at startup
- Check `.startup-state.json` for completed steps
- Re-run missing steps manually
- Ensure scripts are executable (`chmod +x scripts/*.py`)

### Semantic search returns no results
- Rebuild index: `python3 scripts/build-memory-index.py`
- Check Ollama is running: `ollama list`
- Verify vector DB exists: `ls ~/.memory-vectors/`

### Sandman tasks not completing
- Check cron logs: `grep CRON /var/log/syslog`
- Verify subagent spawning works
- Check `.sandman-state.json` for errors

### Session summarization fails
- Ensure session transcript is accessible
- Check `summarize-session-direct.py` output for errors
- Verify `.state.json` is writable

---

## Performance

### Latency
- **Chronological loading:** ~100ms (file reads)
- **Semantic search:** ~2-3s (embedding + vector search)
- **Unsummarized search:** ~100ms cached, ~2-3s first run
- **Session summarization:** ~5-10s per session (LLM-dependent)

### Token Usage
- **Startup context:** ~5-10k tokens (depends on query specificity)
- **Daily rollup:** ~1k tokens per day
- **Sandman analysis:** ~$5/night total budget

### Storage
- **Diary entries:** ~10-50 KB per day
- **Vector index:** ~100-500 MB (grows with memory size)
- **Session transcripts:** Variable (auto-cleanup recommended)

---

## Philosophy

**Memory is limited** - If you want to remember something, WRITE IT TO A FILE.

"Mental notes" don't survive session restarts. Files do.

**During conversation** → append to today's diary
**Quick facts** → add to sticky-notes
**Lessons learned** → update documentation
**Mistakes** → document so future-you doesn't repeat them

**Text > Brain** 📝

---

## Credits

Developed by Josiah for Tiny-Deva (nanobot) and Deva (OpenClaw).

Inspired by:
- Zettelkasten note-taking
- Spaced repetition systems
- Human memory consolidation (sleep, dreams, reflection)
- The "second brain" movement

---

## License

(Add your preferred license here)

---

## Related Documentation

- **Workspace setup:** `AGENTS.md`
- **Core identity:** `SOUL.md`
- **Semantic search:** `scripts/README-load-context-semantic.md`
- **Sandman system:** `scripts/README-sandman.md`
- **Unsummarized search:** `scripts/README-search-unsummarized.md`
- **Verification:** `scripts/README-VERIFICATION.md`

---

**Status:** ✅ Production-ready  
**Version:** 1.0.0  
**Last updated:** 2026-02-02
