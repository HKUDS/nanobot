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

📋 **Ready for Development** — Ralph structure in place with PR-based workflow.

## Workflow: PR-Based Supervision

### Dev Loop (Sonnet via Ralph)
1. Works on feature branch
2. Completes task(s), writes tests
3. At phase end or ~15 tasks: creates PR, **STOPS**
4. Waits for my review

### My Role (Supervisor)

**On PR Notification:**
1. `gh pr view <number>` — read the description
2. `gh pr checkout <number>` — get the code locally
3. `pnpm test` (or `pytest tests/ -v`) — verify tests pass
4. Review the diff — does it match fix_plan.md claims?
5. Check coverage: `pytest --cov=nanobot`
6. Decide:
   - ✅ `gh pr review --approve` → merge → notify Ralph to continue
   - 🔄 `gh pr review --request-changes` → Ralph addresses → re-review

**Mechanical Checks (cron backup):**
- Is the loop running?
- Is there a PR waiting >30 min? → Review now
- Has Ralph been running >2h without PR? → Something's wrong
- Are tests failing repeatedly? → Stop and diagnose

### PR Guardrails
- **Phase boundary:** PR at end of each phase (mandatory)
- **Task count:** PR after ~15 tasks without one
- **Test failures:** PR if stuck on failing tests

### Critical Rules
- **Never rubber-stamp.** Actually review the code.
- **Tests must pass.** No "tests are flaky" exceptions.
- **Verify fix_plan.md.** Sonnet lies about completion.

## Key Files

| File | Purpose |
|------|---------|
| `.ralph/fix_plan.md` | Task list — source of truth |
| `.ralph/PROMPT.md` | Instructions for Sonnet |
| `.ralph/status.json` | Machine-readable state |
| `.ralph/logs/` | Loop and Claude output logs |
| `.claude/skills/pr-checkpoint/` | PR creation skill for Sonnet |
| `CLAUDE.md` | Coding standards |

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
- Set up Ralph structure (.ralph/, .claude/skills/pr-checkpoint/)
- Added hooks for lint/format/test enforcement
- Ready to begin Phase 1 development
