# CLAUDE.md — nanobot Memory Architecture

## Project Overview

nanobot is an ultra-lightweight AI assistant (~4000 lines Python). We're adding a persistent memory system that provides true conversational continuity.

**claw-builder managed project** — Uses PR-based supervision with quality gates.

## Quick Reference

```bash
# Install
pip install -e ".[dev]"

# Test (MUST pass before commits)
pytest tests/ -v

# Lint
ruff check nanobot/

# Format
ruff format nanobot/

# Type check
mypy nanobot/memory/ --ignore-missing-imports

# Coverage
pytest tests/ --cov=nanobot --cov-report=term-missing
```

## Current Focus

Building memory architecture in phases:
1. **Conversation Store** — Every turn embedded and linked (LanceDB)
2. **Memory Agent** — Context synthesis (Haiku-class model)
3. **Triage Agent** — Fast path vs memory lookup routing
4. **Integration** — Wire into agent loop
5. **Dossiers** — Entity knowledge documents
6. **Ingestion** — Post-conversation processing
7. **Streamlined Context** — Replace history with packets
8. **Polish** — Docs and optimization

## Key Constraints

- **Tests required** — Every new file needs tests. No marking done without passing tests.
- **Coverage ≥80%** — New code must be tested
- **One file = one responsibility** — Keep files focused
- **PR review required** — End of phase or every 15 tasks triggers PR

## Coding Standards

- Type hints on all function signatures
- Docstrings on public APIs (Google style)
- Async for I/O and LLM calls
- No magic numbers

## Project Structure

```
nanobot/
├── agent/           # Main loop (modify for memory integration)
├── memory/          # NEW: Our focus
│   ├── store.py     # Conversation turns + embeddings
│   ├── search.py    # Hybrid search
│   ├── curator.py   # Memory agent
│   ├── triage.py    # Triage agent
│   ├── dossier.py   # Entity dossiers
│   └── ingestion.py # Post-processing
├── providers/       # LLM providers
├── channels/        # Chat integrations
└── config/          # Configuration
```

## Task Workflow

1. Read `.claw/WORKPLAN.md` for current task
2. Implement the task
3. Write tests
4. Run `pytest tests/ -v` — must pass
5. Run `ruff check nanobot/` — must pass
6. Mark task `[x]` in WORKPLAN.md
7. Commit with descriptive message
8. At phase end: create PR, wait for review

## Reference Docs

- **PIB:** `.claw/specs/pib.md`
- **WORKPLAN:** `.claw/WORKPLAN.md`
- **PROMPT:** `.claw/PROMPT.md`
- **AGENT:** `.claw/AGENT.md`
- **Config:** `.claw/config.yaml`
