# Supervision Notes — nanobot

## Project Overview

Fork of HKUDS/nanobot — an ultra-lightweight personal AI assistant (~4k lines Python).

We're extending it with an experimental memory architecture:
- **Conversation Store:** Every turn embedded, linked, searchable (vector + BM25)
- **Dossiers:** Living entity documents that evolve over time
- **Memory Agent:** Small LLM that searches, synthesizes context packets
- **Triage Agent:** Routes messages — fast path vs memory lookup path
- **Ingestion Pipeline:** Processes conversations, updates dossiers

Goal: True persistent memory, session-less experience, tight relevant context.

## Current Phase

📋 **Ready for Development** — claw-builder structure in place.

## Workflow: PR-Based Supervision

This project uses the claw-builder PR-based supervision model.

### Dev Loop (Sonnet)
1. Works on feature branch
2. Completes task(s), writes tests
3. At phase end or 15 tasks: creates PR, stops

### My Role (Supervisor)

**Mechanical Checks (cron, every 15-30 min):**
- Is the loop running?
- Is it stuck?
- Has it crashed? → Investigate, fix, restart
- Is there a PR waiting? → Review it
- Has it violated guardrails? → Force PR

**Code Review (PR-triggered):**
- Read the diff
- Run tests myself: `pytest tests/ -v`
- Check coverage: `pytest --cov=nanobot`
- Verify VSA compliance (one file = one responsibility)
- Approve → merge, restart loop
- Request changes → restart loop with feedback

### PR Guardrails
- PR at end of each phase
- PR after max 15 tasks
- PR after 2 validation failures

## Key Decisions

### Architecture (from discussion 2026-02-09)
- Triage agent handles latency by fast-pathing simple queries
- Memory agent does search + synthesis into context packets
- Main agent can ask follow-up questions if memory agent missed something
- Replace traditional chat history with: system prompt + context packet + last few turns
- Dossiers handle temporal changes via versioning ("as of" timestamps)
- Entity extraction probably doable with Haiku, upgrade if needed

### Tech Stack
- **Vector DB:** LanceDB (local, fast, Python-native)
- **BM25:** bm25s (Scipy-based)
- **Embeddings:** sentence-transformers (local)
- **Small models:** claude-3-haiku via litellm

## Quality Gates

- Tests MUST pass before marking task done
- Coverage ≥80% on new code
- Hooks enforce lint/format after edits
- Pre-commit hook runs tests

## Open Questions

1. Best embedding model for conversation retrieval?
2. Optimal hybrid search alpha (vector vs BM25 weight)?
3. Dossier granularity (per person? per project?)

## Session Log

### 2026-02-09

- Forked nanobot from HKUDS/nanobot
- Discussed memory architecture vision with Eric
- Created PIB through interview process
- Designed PR-based supervision workflow
- Set up claw-builder structure (.claw/, .claude/)
- Added hooks for lint/format/test enforcement
- Ready to begin Phase 1 development
