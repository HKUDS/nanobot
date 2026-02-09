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

📋 **PIB Development** — Defining what we're building and why.

## Key Decisions

### Architecture (from discussion 2026-02-09)
- Triage agent handles latency by fast-pathing simple queries
- Memory agent does search + synthesis into context packets  
- Main agent can ask follow-up questions if memory agent missed something
- Replace traditional chat history with: system prompt + context packet + last few turns
- Dossiers handle temporal changes via versioning ("as of" timestamps)
- Entity extraction probably doable with Haiku, upgrade if needed

### Extension Points (documented in docs/EXPERIMENTS.md)
- Context Providers (pluggable context injection)
- Middleware Pipeline (pre/post processing)
- Agent Router (multi-model, parallel execution)
- Response Aggregator (combine parallel responses)

## Open Questions

1. What's the dossier schema? What fields does an entity document have?
2. How granular are dossiers? One per project? Per person? Per concept?
3. What's the ingestion trigger? After each response? Batch?
4. How does memory agent decide "I have enough context"?
5. What's the storage backend? SQLite + sqlite-vec? LanceDB?

## Session Log

### 2026-02-09

- Forked nanobot from HKUDS/nanobot
- Created docs/EXPERIMENTS.md with extension architecture
- Discussed full memory architecture vision with Eric
- Decided to follow proper Ralph workflow: PIB → PRD → Implementation
- Set up .ralph/ directory structure
- Next: Build PIB with Eric
