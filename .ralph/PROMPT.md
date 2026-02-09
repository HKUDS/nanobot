# nanobot Memory Architecture — Claude Code Instructions

You are implementing a persistent memory system for nanobot, an ultra-lightweight AI assistant.

## Project Context

nanobot is a ~4000 line Python AI assistant. We are adding:
1. **Conversation Store** — Every turn persisted, embedded, searchable (vector + BM25)
2. **Dossiers** — Living entity documents that evolve over time
3. **Triage Agent** — Routes messages: fast path vs memory lookup
4. **Memory Agent** — Searches, synthesizes context packets
5. **Ingestion Pipeline** — Processes conversations, updates dossiers

The goal: True persistent memory. Sessions become obsolete. Topic switching is seamless.

## Technical Stack

- **Language:** Python 3.11+
- **Package Manager:** pip / hatch
- **Testing:** pytest, pytest-asyncio
- **Linting:** ruff
- **Embedding:** sentence-transformers (local) or OpenAI API
- **Vector Store:** LanceDB (performant, local, Python-native)
- **BM25:** bm25s (fast, Scipy-based)
- **LLM Calls:** litellm (already in nanobot)

## Project Structure

```
nanobot/
├── agent/           # Existing agent loop
│   ├── loop.py      # Main agent loop (will be modified)
│   ├── context.py   # Context builder (will be modified)
│   └── memory.py    # Current basic memory (will be enhanced)
├── memory/          # NEW: Memory architecture
│   ├── __init__.py
│   ├── store.py     # Conversation store (turns, embeddings, links)
│   ├── dossier.py   # Dossier CRUD and retrieval
│   ├── search.py    # Hybrid search (vector + BM25)
│   ├── embedder.py  # Embedding abstraction
│   ├── triage.py    # Triage agent
│   ├── curator.py   # Memory agent (context packet synthesis)
│   └── ingestion.py # Post-conversation processing
├── providers/       # Existing LLM providers
├── channels/        # Existing chat channels
└── ...
```

## Your Task Protocol

1. Read `.ralph/fix_plan.md` and find the first unchecked item (`- [ ]`)
2. Implement ONLY that one task
3. Write tests for the functionality
4. Run tests: `pytest tests/ -v`
5. Run linting: `ruff check nanobot/`
6. After the task passes tests and linting, mark it with `[x]` in fix_plan.md
7. Commit: `git add -A && git commit -m "feat: [description]"`
8. Output the RALPH_STATUS block

## Coding Standards

- **Type hints required** on all function signatures
- **Docstrings required** on all public functions
- **One file = one responsibility** — keep files focused
- **Tests required** — every new module needs test coverage
- **Async where appropriate** — LLM calls, I/O operations should be async

## Key Implementation Notes

### Conversation Store (Layer 1)
- Use LanceDB for vector storage
- Each turn: id, role, content, embedding, timestamp, channel, prev_turn_id, next_turn_id
- Hybrid search: combine vector similarity + BM25 scores

### Dossiers (Layer 4)
- JSON documents stored in LanceDB or SQLite
- Fields: entity_id, entity_type, name, content, last_updated, version
- Support: create, read, update, search by entity

### Triage Agent (Layer 3)
- Small model (configurable, default: claude-3-haiku)
- Input: user message + last few turns
- Output: { needs_memory: bool, confidence: float, quick_response?: string }
- Sensitivity configurable via slider (1-10)

### Memory Agent (Layer 2)
- Small model for synthesis
- ReAct loop: search → evaluate → search more or synthesize
- Output: context packet (string) for main agent
- Can stream "thinking" updates

### Integration Points
- Modify `agent/loop.py` to route through triage
- Modify `agent/context.py` to accept context packets
- Add memory tools for main agent to request follow-ups

## What NOT To Do

- Don't change the existing channel integrations
- Don't modify the CLI interface (yet)
- Don't add new dependencies without checking pyproject.toml
- Don't implement features beyond the current task
- Don't skip writing tests

## Status Output

At the END of every response, output this block exactly:

---RALPH_STATUS---
STATUS: IN_PROGRESS | BLOCKED | COMPLETE
EXIT_SIGNAL: false | true
RECOMMENDATION: [what to work on next]
---END_RALPH_STATUS---

Rules:
- EXIT_SIGNAL: false while ANY tasks remain in fix_plan.md
- EXIT_SIGNAL: true ONLY when ALL tasks are checked AND tests pass
- If blocked, explain why in RECOMMENDATION
