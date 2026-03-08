# search-unsummarized.py - Semantic Search for Recent Sessions

## Purpose

Fills the gap between real-time conversation and diary entries:
- **Diary entries** are already summarized (covered by `load-context-semantic.py`)
- **Very recent sessions** (< 24hrs) aren't in diary yet
- **This script** searches raw session transcripts to catch fresh context

Solves the "secret word problem" - when users test memory with information from very recent sessions, semantic search can now find it even before summarization.

## How It Works

1. **Find unsummarized sessions**
   - Scans `~/.clawdbot/agents/main/sessions/` for sessions started in last 24hrs
   - Compares against `memory/diary/2026/.state.json` → `lastSummarizedSessionId`
   - Only processes sessions newer than the last summarized one

2. **Smart caching** (`.unsummarized-embeddings/{session_id}.json`)
   - **Cache HIT:** Use stored embeddings (instant ~100ms)
   - **Cache MISS:** Generate via Ollama `qwen3-embedding` (~2-3s)
   - **Storage:** ~1-2KB per session

3. **In-memory vector search**
   - Chunks session transcript text (~200 words per chunk with overlap)
   - Calculates cosine similarity against query embedding
   - Returns top K matches sorted by relevance

4. **Formatted output**
   - Same format as `load-context-semantic.py` (consistent context injection)
   - Groups results by session with timestamps
   - Includes relevance scores for transparency

## Usage

### Basic Search
```bash
python3 scripts/search-unsummarized.py "secret word from recent session"
```

### With Options
```bash
# Adjust relevance threshold
python3 scripts/search-unsummarized.py --query "what did we discuss" --min-score 0.4

# Return more results
python3 scripts/search-unsummarized.py "recent work" --top-k 15

# Look back further (48 hours)
python3 scripts/search-unsummarized.py "yesterday's conversation" --hours 48

# JSON output (for parsing)
python3 scripts/search-unsummarized.py "test" --json
```

### CLI Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `query_words` | positional | - | Query text (space-separated words) |
| `--query` | string | - | Query text (alternative to positional) |
| `--top-k` | int | 10 | Number of results to return |
| `--min-score` | float | 0.3 | Minimum similarity (0.0-1.0) |
| `--hours` | int | 24 | Look back N hours |
| `--json` | flag | false | Output as JSON |

## Integration with AGENTS.md

### Startup Sequence (Step 3)

Current AGENTS.md startup loads diary context with semantic search:
```bash
python3 scripts/load-context-semantic.py "recent work and active projects"
```

**Add this alongside to cover unsummarized sessions:**
```bash
python3 scripts/search-unsummarized.py "recent work and active projects"
```

**Combined approach (maximum coverage):**
```bash
# Load both: diary (summarized) + raw sessions (unsummarized)
python3 scripts/load-context-semantic.py "recent work and active projects"
python3 scripts/search-unsummarized.py "recent work and active projects"
```

### On-Demand Memory Recall

When users ask "what did we...", "do you remember...", use both searches:
```bash
# User: "What was the secret word from our last session?"
python3 scripts/search-unsummarized.py "secret word from recent session"
python3 scripts/load-context-semantic.py "secret word"
```

## Cache Management

### Automatic Cleanup (Daily)

`rollup-daily.py` (runs at 23:59) now includes:
```python
cleanup_embedding_cache()  # Deletes caches for summarized sessions
```

This prevents cache bloat - once a session is summarized into the diary, its raw embedding cache is deleted (diary embeddings are in ChromaDB).

### Manual Cleanup

```bash
# Remove all cached embeddings
rm -rf .unsummarized-embeddings/

# Remove cache for specific session
rm .unsummarized-embeddings/{session_id}.json
```

Cache regenerates automatically on next search.

## Performance Benchmarks

| Scenario | First Search | Cached Search |
|----------|-------------|---------------|
| Single session (3 chunks) | ~2-3s | <100ms |
| Multiple sessions (10 chunks) | ~5-8s | <150ms |
| Heavy load (20 chunks) | ~10-15s | <200ms |

**Cache storage:** ~1-2KB per session (JSONL with chunk text + embeddings)

## Architecture

```
User Query
    ↓
search-unsummarized.py
    ↓
Find unsummarized sessions (last 24hrs)
    ↓
For each session:
    ├─ Check cache (.unsummarized-embeddings/)
    ├─ If cached: load embeddings
    └─ If not: chunk text → embed → save cache
    ↓
In-memory cosine similarity search
    ↓
Return top K matches (formatted)
```

## Comparison with load-context-semantic.py

| Feature | load-context-semantic.py | search-unsummarized.py |
|---------|--------------------------|------------------------|
| **Data source** | Diary entries (summarized) | Raw session transcripts |
| **Time coverage** | All time (indexed) | Last 24hrs (dynamic) |
| **Storage** | ChromaDB (persistent) | JSONL cache (temporary) |
| **Indexing** | Manual rebuild (`build-memory-index.py`) | Auto on-demand |
| **Cleanup** | Manual | Auto (daily rollup) |
| **Use case** | Long-term memory recall | Very recent context |

**Best practice:** Use both together for comprehensive coverage.

## Troubleshooting

### "No unsummarized sessions found"
- Check if sessions exist: `ls ~/.clawdbot/agents/main/sessions/*.jsonl`
- Verify state file: `cat memory/diary/2026/.state.json`
- Try increasing `--hours` parameter

### "Error getting embedding"
- Ensure Ollama is running: `ollama list`
- Check model: `ollama pull qwen3-embedding`
- Test Ollama API: `curl http://localhost:11434/api/embeddings -d '{"model":"qwen3-embedding","prompt":"test"}'`

### Cache issues
- Clear cache: `rm -rf .unsummarized-embeddings/`
- Check disk space: `df -h .`
- Verify permissions: `ls -la .unsummarized-embeddings/`

## Future Enhancements

Potential improvements (not yet implemented):
- **Hybrid search:** Combine keyword + semantic for better recall
- **Incremental caching:** Update cache on new messages (real-time)
- **Multi-modal:** Include tool outputs, errors, metadata in chunks
- **Importance filtering:** De-prioritize heartbeats, routine checks
- **Cross-session linking:** Track conversation threads across sessions

## Reference Implementation

Built using patterns from:
- `scripts/load-context-semantic.py` - semantic search on diary
- `scripts/build-memory-index.py` - chunking + embedding generation  
- `scripts/summarize-session-direct.py` - JSONL parsing

See source code for detailed implementation.
