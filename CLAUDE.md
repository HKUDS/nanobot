# CLAUDE.md — nanobot Memory Architecture

## Project Overview

nanobot is an ultra-lightweight AI assistant (~4000 lines Python). We're adding a persistent memory system that provides true conversational continuity.

## Quick Reference

```bash
# Install
pip install -e ".[dev]"

# Test
pytest tests/ -v

# Lint
ruff check nanobot/

# Format
ruff format nanobot/
```

## Current Focus

Building a memory architecture with:
1. **Conversation Store** — Every turn embedded and linked
2. **Hybrid Search** — Vector + BM25
3. **Triage Agent** — Routes fast vs memory path
4. **Memory Agent** — Synthesizes context packets
5. **Dossiers** — Entity knowledge documents

## Key Decisions

- **Vector DB:** LanceDB (local, fast, Python-native)
- **BM25:** bm25s (Scipy-based, fast)
- **Embeddings:** sentence-transformers (local) or OpenAI
- **Small Models:** claude-3-haiku via litellm

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
└── channels/        # Chat integrations
```

## Coding Standards

- Type hints on all functions
- Docstrings on public APIs
- Tests for every new module
- Async for I/O operations
- One responsibility per file

## Task Workflow

See `.ralph/fix_plan.md` for current tasks. Work on the first unchecked `- [ ]` item, test it, then mark it `- [x]`.

## Reference Docs

- PIB: `.ralph/specs/pib.md`
- Agent instructions: `.ralph/AGENT.md`
- Full prompt: `.ralph/PROMPT.md`
