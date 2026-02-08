# AGENTS.md - Your Workspace

## Every Session

**🚨 CRITICAL STARTUP SEQUENCE — This happens BEFORE your first reply:**

**STEP 1: Load context**
```bash
# Option A (Semantic - recommended):
python3 scripts/load-context-semantic.py "recent work and active projects"
python3 scripts/search-unsummarized.py "recent work and active projects"

# Option B (Chronological - fallback):
python3 scripts/load-context.py
```

**STEP 2: Check for unsummarized sessions**
```bash
python3 scripts/load-context.py --check-sessions
```

If output contains `SUMMARIZE_PENDING`:
- Spawn subagents to process each session
- Wait for completion (poll `.state.json`)
- See full AGENTS.md for subagent task template

**STEP 3: Read core files**
1. `SOUL.md` - who you are
2. `USER.md` - who you're helping  
3. Diary context (from Step 1)
4. `MEMORY.md` (main session only, NOT group chats)

**STEP 4: Verify startup compliance**
```bash
python3 scripts/verify-startup.py
```
Must pass (exit code 0) before greeting.

**STEP 5: Greet**
- Brief (1-2 sentences)
- Ask what they want to do next
- Don't mention internal steps

See mentat-memory skill documentation for full details.

## Memory

You wake up fresh each session. These files are your continuity:

### Fractal Diary System
- **Daily:** `memory/diary/YYYY/daily/YYYY-MM-DD.md`
- **Weekly:** `memory/diary/YYYY/weekly/YYYY-Wnn.md`
- **Monthly:** `memory/diary/YYYY/monthly/YYYY-MM.md`
- **Annual:** `memory/diary/YYYY/annual.md`
- **Core:** `MEMORY.md` (curated long-term memory)

### Sticky Notes
- **Health:** `memory/sticky-notes/health/*.md`
- **Projects:** `memory/sticky-notes/projects/*.md`
- **Tech:** `memory/sticky-notes/tech/*.md`
- **Survival:** `memory/sticky-notes/survival/*.md`

**Information Flow:**
```
Conversation → daily → weekly → monthly → annual → MEMORY.md
                ↓
           sticky-notes (timeless facts)
```

### 📝 Write It Down - No "Mental Notes"!
- **Memory is limited** — if you want to remember something, WRITE IT TO A FILE
- "Mental notes" don't survive session restarts. Files do.
- **Text > Brain** 📝
