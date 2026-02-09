# nanobot Memory Architecture — Claude Code Instructions

You are implementing a persistent memory system for nanobot, an ultra-lightweight AI assistant.

## Reference Documentation

**Read these before starting:**
- `.ralph/docs/codebase.md` — nanobot architecture and integration points
- `.ralph/docs/lancedb.md` — LanceDB API patterns
- `.ralph/docs/bm25s.md` — bm25s API patterns
- `.ralph/docs/sentence-transformers.md` — Embedding patterns
- `.ralph/specs/pib.md` — Product requirements
- `.ralph/specs/stdlib/CODING.md` — VSA coding standards

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
- **Type Checking:** mypy
- **Embedding:** sentence-transformers (all-MiniLM-L6-v2, 384 dims)
- **Vector Store:** LanceDB (local, embedded)
- **BM25:** bm25s (Scipy-based)
- **LLM Calls:** litellm (already in nanobot)

## Project Structure

```
nanobot/
├── agent/           # Existing agent loop (modify for integration)
│   ├── loop.py      # AgentLoop — main processing engine
│   ├── context.py   # ContextBuilder — where memory integrates
│   └── memory.py    # Old memory (we're replacing this)
├── memory/          # NEW: Memory architecture
│   ├── __init__.py
│   ├── store.py     # Conversation turns, embeddings, links
│   ├── dossier.py   # Entity dossiers
│   ├── search.py    # Hybrid vector + BM25 search
│   ├── embedder.py  # Embedding abstraction
│   ├── triage.py    # Triage agent
│   ├── curator.py   # Memory agent (context synthesis)
│   └── ingestion.py # Post-conversation processing
├── providers/       # Existing LLM providers
├── channels/        # Existing chat channels
└── config/          # Configuration (add memory settings)
```

## Your Task Protocol

1. Read `.ralph/fix_plan.md` and find the first unchecked item (`- [ ]`)
2. Implement ONLY that one task
3. Write tests for the functionality (REQUIRED — tests must pass)
4. Run tests: `pytest tests/ -v`
5. Run linting: `ruff check nanobot/`
6. Run type check: `mypy nanobot/memory/ --ignore-missing-imports`
7. After ALL checks pass, mark the task with `[x]` in fix_plan.md
8. Commit with descriptive message: `git add -A && git commit -m "feat: [description]"`
9. Check if you've hit a PR checkpoint (see below)

## PR Checkpoint Workflow — CRITICAL

You have a skill at `.claude/skills/pr-checkpoint/SKILL.md` that explains when and how to create PRs.

**You MUST create a PR and STOP working when:**
- You complete a phase (all tasks in a phase section checked)
- You've completed ~15 tasks since the last PR
- You're about to make a major architectural change
- Tests are failing and you're unsure of the fix

**After creating a PR:**
- Do NOT continue working
- Wait for supervisor (Kai) to review
- Your last action should be reporting you've created a PR

## Coding Standards

- **Type hints required** on all function signatures
- **Docstrings required** on all public functions (Google style)
- **One file = one responsibility** — keep files focused (<300 lines ideal)
- **Tests required** — every new module needs corresponding test file
- **Async where appropriate** — LLM calls, I/O operations should be async
- **No magic numbers** — use constants or config
- **Follow VSA** — see `.ralph/specs/stdlib/CODING.md`

## Test Requirements

**Every task that creates or modifies code MUST include tests.**

When you create `nanobot/memory/foo.py`, you MUST also create `tests/test_foo.py`.

Tests should:
- Cover the happy path
- Cover at least one error case
- Use mocks for external dependencies (LLM calls, filesystem)
- Be runnable with `pytest tests/test_foo.py -v`

**Do not mark a task complete if tests don't exist or don't pass.**

## Key Implementation Notes

### Conversation Store (Phase 1)
- Use LanceDB for vector storage (see `.ralph/docs/lancedb.md`)
- Use sentence-transformers for embeddings (see `.ralph/docs/sentence-transformers.md`)
- Each turn: id, role, content, embedding, timestamp, channel, prev_turn_id, next_turn_id
- Hybrid search: combine vector similarity + BM25 scores with configurable alpha

### Dossiers (Phase 5)
- JSON documents stored in LanceDB
- Fields: entity_id, entity_type, name, content, last_updated, version
- Support: create, read, update, delete, search

### Triage Agent (Phase 3)
- Small model (configurable, default: claude-3-haiku)
- Input: user message + last few turns
- Output: TriageResult(needs_memory: bool, confidence: float, quick_response: str | None)
- Sensitivity configurable via slider (1-10)

### Memory Agent (Phase 2)
- Small model for synthesis
- ReAct loop: search → evaluate → search more or synthesize
- Output: context packet (string) for main agent
- Can stream "thinking" updates

## What NOT To Do

- Don't change the existing channel integrations
- Don't modify the CLI interface
- Don't skip writing tests
- Don't implement features beyond the current task
- Don't mark tasks complete if tests fail
- Don't add dependencies without updating pyproject.toml
- **Don't continue past a PR checkpoint without approval**

## Definition of Done (Per Task)

A task is DONE when:
1. Code is written and follows standards
2. Tests exist and pass
3. Linting passes
4. Type checking passes
5. Task checkbox is marked `[x]` in fix_plan.md
6. Work is committed

A phase is DONE when:
1. All phase tasks are checked
2. All tests pass
3. PR is created and **approved by supervisor**
