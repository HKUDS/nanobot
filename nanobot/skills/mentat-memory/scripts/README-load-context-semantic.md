# Semantic Memory Context Loader

**Script:** `scripts/load-context-semantic.py`  
**Purpose:** Load diary context using vector search instead of naive chronological file reading  
**Status:** Implemented, ready for integration

---

## Overview

Traditional `load-context.py` loads diary entries chronologically (today → this week → this month → this year). While this provides temporal context, it doesn't guarantee **relevant** information surfaces based on the current conversation topic.

`load-context-semantic.py` solves this by:
1. Accepting a query parameter (user message or session context)
2. Embedding the query using local Ollama (qwen3-embedding)
3. Searching the ChromaDB memory index for semantically similar chunks
4. Returning top-K results ranked by relevance
5. Formatting output for agent context injection

---

## Key Features

### ✅ Semantic Retrieval
- **Query-driven context loading** instead of fixed chronological order
- Finds relevant memories even if buried in older diary entries
- Ranks results by similarity score (cosine distance)

### ✅ Local & Fast
- Uses local Ollama embeddings (qwen3-embedding)
- No API costs after initial setup
- ~2-3 seconds for query → results
- ChromaDB persistent storage at `~/.memory-vectors`

### ✅ Fallback Support
- Gracefully falls back to chronological loading if vector DB unavailable
- Compatible with existing `load-context.py` workflow
- `--chronological` flag forces traditional behavior

### ✅ Flexible Usage
- Can be invoked with any query (natural language)
- Adjustable `--top-k` (result count) and `--min-score` (relevance threshold)
- JSON output mode for programmatic parsing
- Defaults to "recent work and active projects" if no query provided

---

## Usage Examples

### Basic Search
```bash
# Find memories about specific topic
python3 scripts/load-context-semantic.py "sandman implementation"

# Search with user's current question
python3 scripts/load-context-semantic.py "what was the secret word from our last session?"

# Broader context query
python3 scripts/load-context-semantic.py "recent decisions and active projects"
```

### Advanced Options
```bash
# Return more results (default: 10)
python3 scripts/load-context-semantic.py --query "memory system" --top-k 20

# Stricter relevance threshold (default: 0.3)
python3 scripts/load-context-semantic.py --query "telegram integration" --min-score 0.5

# JSON output for parsing
python3 scripts/load-context-semantic.py "sandman" --json
```

### Fallback Modes
```bash
# Force chronological loading (bypass vector search)
python3 scripts/load-context-semantic.py --chronological

# No query = defaults to recent context
python3 scripts/load-context-semantic.py
```

---

## Output Format

### Standard Mode (Human-Readable)
```
=== SEMANTIC MEMORY CONTEXT ===
Query: sandman implementation
Found 10 relevant memory chunks

--- memory/diary/2026/daily/2026-01-29.md ---
[Date: 2026-01-29 | Relevance: 0.842]
<chunk text with relevant content>

--- memory/sticky-notes/projects/sandman.md ---
[Date: 2026-01-28 | Relevance: 0.756]
<chunk text>
...
```

Results are grouped by source file, ranked by relevance within each file.

### JSON Mode (Programmatic)
```json
{
  "query": "sandman implementation",
  "results": [
    {
      "text": "<chunk content>",
      "metadata": {
        "source_file": "memory/diary/2026/daily/2026-01-29.md",
        "date": "2026-01-29"
      },
      "score": 0.842
    }
  ]
}
```

---

## Integration Strategies

### Strategy 1: Replace load-context.py
**When:** Agent always needs semantic retrieval

**Implementation:**
```python
# In AGENTS.md startup sequence, replace:
python3 scripts/load-context.py

# With:
python3 scripts/load-context-semantic.py "recent work and active projects"
```

**Pros:** Always loads relevant context  
**Cons:** Requires query formulation at startup

---

### Strategy 2: Hybrid Approach (Recommended)
**When:** Want both temporal and semantic context

**Implementation:**
```python
# Load chronological baseline
chronological_context = exec("python3 scripts/load-context.py")

# Enhance with semantic search based on current conversation
if user_message:
    semantic_context = exec(f"python3 scripts/load-context-semantic.py '{user_message}'")
```

**Pros:** Best of both worlds  
**Cons:** Slightly higher latency (2x load time)

---

### Strategy 3: On-Demand Retrieval
**When:** Agent needs specific recall during conversation

**Implementation:**
```python
# Agent detects recall request ("what did we...", "do you remember...")
if is_recall_question(user_message):
    context = exec(f"python3 scripts/load-context-semantic.py '{user_message}'")
    # Use context to answer question
```

**Pros:** Only runs when needed  
**Cons:** Doesn't preload relevant context at startup

---

### Strategy 4: Smart Query Generation
**When:** Want to infer user's likely information needs

**Implementation:**
```python
# At startup, generate query based on session context
recent_topics = get_recent_session_topics()  # From session history
user_location = get_user_context()  # Time of day, recent activity

query = f"Information about {recent_topics} and any pending tasks"
context = exec(f"python3 scripts/load-context-semantic.py '{query}'")
```

**Pros:** Intelligent, adaptive context loading  
**Cons:** Requires additional logic to generate good queries

---

## Prerequisites

### 1. ChromaDB Memory Index
Build the index first (if not already done):
```bash
python3 scripts/build-memory-index.py
```

This indexes:
- `memory/diary/YYYY/daily/*.md`
- `memory/diary/YYYY/weekly/*.md`
- `memory/diary/YYYY/monthly/*.md`
- `memory/sticky-notes/**/*.md`

**Rebuild after major memory updates** to keep index fresh.

### 2. Ollama with qwen3-embedding
Ensure Ollama is running with the embedding model:
```bash
ollama pull qwen3-embedding
ollama list  # Verify it's available
```

### 3. Python Dependencies
The script uses ChromaDB for vector storage:
```bash
# Already installed in whisper-venv
source ~/.whisper-venv/bin/activate
pip install chromadb
```

---

## Technical Details

### Embedding Model
- **Model:** qwen3-embedding (Ollama)
- **Dimensions:** 1024 (high quality)
- **Speed:** ~2-3s per query embedding
- **Cost:** Free (local)

### Vector Database
- **DB:** ChromaDB (persistent)
- **Storage:** `~/.memory-vectors/`
- **Distance metric:** L2 (Euclidean)
- **Similarity conversion:** `score = 1.0 - (distance / 2.0)`

### Chunking Strategy
Inherited from `build-memory-index.py`:
- Chunks diary entries by paragraph/section
- Preserves markdown structure
- Includes source file and date metadata

---

## Comparison: Semantic vs. Chronological

| Aspect | Chronological | Semantic |
|--------|---------------|----------|
| **Order** | Fixed (today → week → month → year) | Ranked by relevance |
| **Speed** | Instant (file reads) | 2-3s (embedding + search) |
| **Relevance** | Temporal proximity | Semantic similarity |
| **Query-aware** | ❌ No | ✅ Yes |
| **Finds old info** | ❌ Only if in recent files | ✅ Yes, if relevant |
| **Token efficiency** | Wastes tokens on irrelevant context | Optimizes for relevance |

### When to Use Each

**Use chronological when:**
- User asks "what happened today?"
- Need temporal continuity
- Want to see progression over time
- Vector search unavailable

**Use semantic when:**
- User asks specific questions ("what was X?")
- Need targeted recall
- Want to avoid attention bias issues
- Context window is limited

---

## Known Limitations

1. **Index freshness:** Requires manual rebuild after diary updates
   - **Solution:** Add cron job to rebuild nightly
   
2. **Query quality matters:** Vague queries return vague results
   - **Solution:** Generate specific queries from user context

3. **No cross-session context:** Doesn't load session transcripts directly
   - **Solution:** Diary summaries must be well-written

4. **ChromaDB dependency:** Requires additional setup
   - **Solution:** Falls back to chronological if unavailable

---

## Future Enhancements

### 🔮 Possible Improvements

1. **Auto-query generation**
   - Infer user's information needs from recent conversation
   - "What does the user probably want to know?"

2. **Hybrid scoring**
   - Combine semantic similarity + temporal recency
   - Boost recent memories with high semantic match

3. **Multi-query search**
   - Run multiple sub-queries in parallel
   - Aggregate results for broader coverage

4. **Incremental indexing**
   - Auto-detect new diary entries
   - Update index without full rebuild

5. **Result caching**
   - Cache frequent queries
   - Reduce embedding overhead for common patterns

6. **OpenClaw memory tool integration**
   - Expose as native `openclaw memory search-semantic` command
   - Use OpenClaw's built-in vector providers if configured

---

## Testing

### Test Cases

**1. Recent topic recall**
```bash
python3 scripts/load-context-semantic.py "sandman overnight analysis"
# Expected: Finds recent diary entries about Sandman implementation
```

**2. Specific fact retrieval**
```bash
python3 scripts/load-context-semantic.py "what is the secret word?"
# Expected: Finds session where secret word was mentioned
```

**3. Broad context query**
```bash
python3 scripts/load-context-semantic.py "active projects and recent decisions"
# Expected: Mix of project sticky-notes and recent diary summaries
```

**4. Fallback behavior**
```bash
# Temporarily rename vector DB
mv ~/.memory-vectors ~/.memory-vectors.bak
python3 scripts/load-context-semantic.py "test query"
# Expected: Falls back to chronological, outputs standard diary sections
mv ~/.memory-vectors.bak ~/.memory-vectors
```

**5. JSON output parsing**
```bash
python3 scripts/load-context-semantic.py "sandman" --json | jq '.results | length'
# Expected: Number of results (should be ≤ top-k)
```

---

## Maintenance

### Regular Tasks

**Daily:**
- No action needed (script pulls from existing index)

**Weekly:**
- Review search quality
- Check if common queries return good results

**After major diary updates:**
```bash
python3 scripts/build-memory-index.py
```

**Monthly:**
- Evaluate index size (ChromaDB storage)
- Clean up old/irrelevant memories if needed

---

## Related Documentation

- **Vector search skill:** `skills/memory-search-local/SKILL.md`
- **Original loader:** `scripts/load-context.py`
- **Index builder:** `scripts/build-memory-index.py`
- **Memory system:** `memory/README.md`
- **Investigation report:** `MEMORY-SYSTEM-INVESTIGATION-REPORT.md`

---

**Status:** ✅ Ready for production use  
**Next step:** Update AGENTS.md startup sequence to integrate semantic loading
