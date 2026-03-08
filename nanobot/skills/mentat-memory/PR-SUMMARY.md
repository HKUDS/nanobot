# mentat-memory Skill - Pull Request Summary

## What This Is

A complete fractal memory system for AI agents that provides long-term continuity across sessions. Think of it as "sleep and dreams" for AI - consolidating daily experiences into lasting knowledge.

## Key Features

### 🧠 Fractal Memory Hierarchy
- **Daily logs** → **Weekly summaries** → **Monthly trajectories** → **Annual themes** → **Core memory**
- Each level compresses and consolidates the level below
- Information flows naturally from raw logs to curated knowledge

### 🔍 Semantic Search
- Query-driven context loading instead of naive chronological reading
- Finds relevant memories even if buried in old diary entries
- Uses local Ollama embeddings (no API costs)
- +60% recall accuracy vs chronological loading

### 📝 Session Summarization
- Automatic conversion of session transcripts to diary entries
- Parallel subagent processing for batch summarization
- Tracks summarization state to avoid duplicates

### 🌙 Sandman Overnight Analysis
- Autonomous overnight processing of the day's sessions
- 6 parallel analysis tasks (enforcement, patterns, consistency, projects, self-analysis, optimization)
- $5/night dedicated budget
- Morning summary delivered at 6:00 AM

### 🗂️ Sticky-Notes System
- Timeless reference knowledge organized by domain
- Health, projects, tech, survival categories
- Separate from temporal diary entries

## What's Included

```
skills/mentat-memory/
├── SKILL.md                    # Complete documentation
├── README.md                   # Quick start guide
├── PR-SUMMARY.md              # This file
├── AGENTS.template.md         # Starter workspace setup
├── MEMORY.template.md         # Starter memory file
└── scripts/                   # All memory management scripts
    ├── load-context.py
    ├── load-context-semantic.py
    ├── search-unsummarized.py
    ├── rollup-daily.py
    ├── rollup-weekly.py
    ├── rollup-monthly.py
    ├── summarize-session-direct.py
    ├── build-memory-index.py
    ├── sandman-nanobot.py
    ├── verify-startup.py
    └── README-*.md            # Detailed guides
```

## What's NOT Included

Personal memory files are gitignored:
- `memory/MEMORY.md` (actual long-term memory)
- `memory/diary/` (session logs)
- `memory/sticky-notes/` (reference notes)
- `USER.md`, `TOOLS.md`, `HEARTBEAT.md`

The `.gitignore` is configured to protect privacy.

## Installation

1. Copy template files to workspace root
2. Create directory structure (`memory/diary/`, `memory/sticky-notes/`)
3. Install optional dependencies (ChromaDB for semantic search)
4. Set up Ollama with `qwen3-embedding` (optional)
5. Build vector index (optional)

See `skills/mentat-memory/README.md` for detailed setup.

## Usage

### Agent Startup Sequence
```python
# Load context (semantic or chronological)
exec("python3 scripts/load-context-semantic.py 'recent work'")

# Search very recent sessions not yet in diary
exec("python3 scripts/search-unsummarized.py 'recent work'")

# Check for pending summarization
exec("python3 scripts/load-context.py --check-sessions")

# Verify compliance
exec("python3 scripts/verify-startup.py")
```

### Memory Consolidation (automated via cron)
- **Daily (23:59):** Rollup today → this week
- **Weekly (Sun 23:59):** Rollup week → this month
- **Monthly (EOM):** Rollup month → annual
- **Overnight (3:00 AM):** Sandman analysis

## Platform Compatibility

Designed for nanobot but should work with any agent platform that supports:
- Python script execution
- File read/write
- Subagent spawning (optional, for Sandman)

Adapt the startup sequence to your platform's tool interface.

## Performance

- **Chronological loading:** ~100ms
- **Semantic search:** ~2-3s
- **Session summarization:** ~5-10s per session
- **Startup context:** ~5-10k tokens

## Philosophy

**"Memory is limited - if you want to remember something, WRITE IT TO A FILE."**

This system enforces that principle by providing:
- Clear information flow (conversation → files → consolidation)
- Automatic cleanup and compression
- Semantic retrieval for intelligent recall
- Privacy protection for sensitive data

## Credits

Developed by Josiah for Tiny-Deva (nanobot) and Deva (OpenClaw).

Inspired by:
- Zettelkasten note-taking
- Spaced repetition systems
- Human memory consolidation (sleep, dreams, reflection)
- The "second brain" movement

## Testing

Tested in production since 2026-01-26 with:
- 100+ session summarizations
- Daily/weekly/monthly rollups
- Semantic search queries
- Sandman overnight analysis
- Startup verification

## License

(Add your preferred license)

---

**Status:** ✅ Production-ready  
**Version:** 1.0.0  
**Date:** 2026-02-02
