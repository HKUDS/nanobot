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
- **Type Checking:** mypy
- **Embedding:** sentence-transformers (local) or OpenAI API
- **Vector Store:** LanceDB (performant, local, Python-native)
- **BM25:** bm25s (fast, Scipy-based)
- **LLM Calls:** litellm (already in nanobot)

## Project Structure

```
nanobot/
├── agent/           # Existing agent loop (modify for integration)
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

1. Read `.claw/WORKPLAN.md` and find the first unchecked item (`- [ ]`)
2. Implement ONLY that one task
3. Write tests for the functionality (REQUIRED — tests must pass)
4. Run tests: `pytest tests/ -v`
5. Run linting: `ruff check nanobot/`
6. Run type check: `mypy nanobot/memory/ --ignore-missing-imports`
7. After ALL checks pass, mark the task with `[x]` in WORKPLAN.md
8. Commit with descriptive message: `git add -A && git commit -m "feat: [description]"`
9. Output the CLAW_STATUS block

## Coding Standards

- **Type hints required** on all function signatures
- **Docstrings required** on all public functions (Google style)
- **One file = one responsibility** — keep files focused (<300 lines ideal)
- **Tests required** — every new module needs corresponding test file
- **Async where appropriate** — LLM calls, I/O operations should be async
- **No magic numbers** — use constants or config

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
- Use LanceDB for vector storage
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

## PR Workflow

When a phase is complete OR after 15 tasks, you will create a PR for review:

1. Push your branch: `git push origin <branch-name>`
2. Create PR: `gh pr create --title "Phase N: [summary]" --body "[task list]"`
3. Output `CLAW_STATUS` with `EXIT_SIGNAL: true` and `AWAITING_REVIEW: true`
4. Wait for supervisor review

Do NOT continue working until the PR is approved.

## Status Output

At the END of every response, output this block exactly:

```
---CLAW_STATUS---
STATE: CODING | VALIDATING | AWAITING_REVIEW | ADDRESS_FEEDBACK
STATUS: IN_PROGRESS | BLOCKED | PHASE_COMPLETE
EXIT_SIGNAL: false | true
AWAITING_REVIEW: false | true
TASKS_DONE: N
TASKS_REMAINING: M
RECOMMENDATION: [what to work on next or what's blocking]
---END_CLAW_STATUS---
```

Rules:
- EXIT_SIGNAL: false while working on tasks
- EXIT_SIGNAL: true when phase complete or PR created
- AWAITING_REVIEW: true only when PR is created and waiting for review
- If blocked, explain why in RECOMMENDATION
