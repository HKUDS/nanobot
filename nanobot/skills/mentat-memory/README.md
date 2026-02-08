# mentat-memory Skill

**Fractal memory system for AI agents with long-term continuity**

## Quick Start

1. **Copy template files to your workspace root:**
   ```bash
   cp AGENTS.template.md ../../AGENTS.md
   cp MEMORY.template.md ../../memory/MEMORY.md
   ```

2. **Install Python dependencies:**
   ```bash
   pip install chromadb  # Optional: for semantic search
   ```

3. **Set up Ollama (optional, for semantic search):**
   ```bash
   ollama pull qwen3-embedding
   ```

4. **Create directory structure:**
   ```bash
   mkdir -p memory/diary/$(date +%Y)/{daily,weekly,monthly}
   mkdir -p memory/sticky-notes/{health,projects,tech,survival}
   ```

5. **Build vector index (optional):**
   ```bash
   python3 scripts/build-memory-index.py
   ```

6. **Test startup sequence:**
   ```bash
   python3 scripts/load-context-semantic.py "test query"
   python3 scripts/verify-startup.py
   ```

## What's Included

- **Scripts:** All memory management scripts (`scripts/`)
- **Documentation:** Full guides (`scripts/README-*.md`)
- **Templates:** Starter files for AGENTS.md and MEMORY.md
- **Skill guide:** This file and SKILL.md

## What's NOT Included

Your personal memory files are gitignored:
- `memory/MEMORY.md` (your actual long-term memory)
- `memory/diary/` (your session logs)
- `memory/sticky-notes/` (your reference notes)
- `USER.md`, `TOOLS.md`, `HEARTBEAT.md`

These are YOUR data - keep them private!

## Documentation

- **SKILL.md** - Complete system documentation
- **scripts/README-load-context-semantic.md** - Semantic search guide
- **scripts/README-sandman.md** - Overnight analysis system
- **scripts/README-search-unsummarized.md** - Recent session search
- **scripts/README-VERIFICATION.md** - Startup verification

## Support

This skill was developed for nanobot but should work with any agent platform that supports:
- Python script execution
- File read/write
- Subagent spawning (optional, for Sandman)

Adapt the startup sequence in AGENTS.md to your platform's tool interface.

---

**Version:** 1.0.0  
**License:** (Add your license)  
**Author:** Josiah
