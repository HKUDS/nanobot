# Memory Separation Proposal (Semantic vs Episodic)

Date: 2026-03-01
Owner: nanobot memory subsystem
Status: Proposed

## Objective
Improve memory quality by separating **semantic** and **episodic** behavior using a single Mem0 backend, with lightweight metadata + retrieval policies + measurable rollout gates.

## Executive Summary
Keep one Mem0 instance. Do not create separate vector stores/services initially.

Introduce separation at four layers:
1. Write-time schema and classification.
2. Retrieval-time routing and re-ranking.
3. Context assembly and token budgets.
4. Evaluation metrics and phased rollout.

This is primarily a retrieval-policy and data-quality project, not an infrastructure project.

## Problem Statement
Current behavior mixes long-lived facts and timeline events in one retrieval flow. This causes:
- Episodic incidents to leak into generic prompts.
- Stale event noise in context.
- Harder contradiction handling for stable facts/preferences.
- Weak control over relevance vs recency tradeoffs.

## Design Principles
- Single backend first: minimize operational complexity.
- Deterministic policy before model-heavy policy.
- Type-aware lifecycle semantics.
- Evidence-aware reflection safety.
- Measurable improvements or no rollout.

## Target Memory Model
### Memory Types
- `semantic`: stable, reusable facts/preferences/constraints.
- `episodic`: event timeline and what happened.
- `reflection`: derived insight with evidence links.

### Canonical Metadata (required)
- `memory_type`: `semantic|episodic|reflection`
- `topic`: controlled taxonomy (`infra`, `deploy`, `user_pref`, etc.)
- `stability`: `high|medium|low`
- `source`: `chat|tool|reflection`
- `confidence`: float in `[0,1]`
- `timestamp`: ISO UTC
- `ttl_days`: optional (primarily episodic/reflection)
- `evidence_refs`: optional list of source event/tool IDs

## Write Policy
### Deterministic Rules
- Preference/fact/constraint updates -> semantic update/write.
- Incident/progress/attempt logs -> episodic append.
- Mixed messages -> dual-write:
  - distilled semantic fact
  - original episodic event

### Ambiguity Handling
- Start rule-based.
- Use LLM-assisted classification only for ambiguous cases.
- Low-confidence classification defaults to episodic + low stability + short TTL.

## Retrieval Router
### Intent Modes
- `fact_lookup`: semantic-heavy (target 80/20 semantic/episodic)
- `debug_history`: episodic-heavy (target 30/70)
- `planning`: mixed (target 60/40)
- `reflection`: reflection allowed only with evidence gating

### Retrieval Mechanics
1. Retrieve larger candidate pool (`top_k * 3` to `top_k * 4`).
2. Apply metadata filters by mode.
3. Re-rank by policy score:

`final_score = similarity + recency + stability + intent_boost - stale_penalty`

4. Enforce section caps (semantic first unless mode overrides).

### Why this approach
Post-filtering can reduce recall if top-k is too small. Candidate expansion + local reranking mitigates this without requiring multi-index architecture.

## Context Assembly Policy
- Semantic memory is always included (compact, high-signal).
- Episodic memory is conditional on intent (debug/history/continuation).
- Reflection memory is optional and capped.

### Token Budget Targets
- Semantic: 50-60%
- Episodic: 30-40%
- Reflection: <=10%

### Noise Controls
- Age decay for episodic memories.
- Suppress stale low-stability incidents by default.
- Keep unresolved recent tasks/decisions visible with limits.

## Conflict and Lifecycle Strategy
### Semantic
- Supports contradiction tracking and supersession.
- Metadata fields include status/confidence and optional `supersedes_memory_id`.

### Episodic
- Treated as timeline records (append-only bias).
- Prefer state transitions (`open|resolved`) over deletion.

### Reflection
- Never overrides semantic directly.
- Requires evidence refs.
- Lower default rank and shorter TTL.

## Metrics and Evaluation
### Online Metrics
- `retrieval_candidates`, `retrieval_returned`
- returned counts by type (`semantic`, `episodic`, `reflection`)
- section token usage by type
- contradictions opened/resolved
- context truncation frequency

### Offline Eval Set
Build 30-100 labeled prompts:
- fact retrieval precision@k
- debug incident recall@k
- contradiction regression count
- context token cost delta

### Rollout Gates
Ship only if:
- Fact precision improves materially.
- Debug/history recall does not regress.
- Token cost is reduced or stable.

## Implementation Phases
### Phase 1: Baseline Instrumentation
- Add retrieval/context metrics and logs.
- No behavior changes.

### Phase 2: Metadata Contract
- Enforce normalized write schema and defaults.
- Add validation and migration defaults for old entries.

### Phase 3: Write Classifier + Dual-write
- Implement deterministic classifier.
- Add dual-write path for mixed content.

### Phase 4: Retrieval Router + Re-rank
- Add intent-aware routing and scoring.
- Candidate expansion and filter/re-rank.

### Phase 5: Context Gating
- Conditional episodic/reflection sections.
- Token budget enforcement per section.

### Phase 6: Lifecycle and Conflict Hardening
- Semantic supersession behavior.
- Episodic resolution-state handling.

### Phase 7: Reflection Safety
- Evidence requirements and ranking penalties.

### Phase 8: Eval + Rollout
- A/B flags, shadow mode, gradual rollout, rollback switches.

## Proposed Config Flags
- `memory_type_separation_enabled`
- `memory_router_enabled`
- `memory_reflection_enabled`
- `memory_candidate_multiplier`
- `memory_section_token_caps`
- `memory_debug_logging`

## Risks
- Misclassification noise can degrade retrieval.
- Overfitted intent heuristics may fail cross-domain.
- Legacy memories lacking metadata reduce filter quality.

## Mitigations
- Conservative defaults and rule-based start.
- Shadow mode telemetry before activation.
- Backfill metadata with safe defaults and incremental rescore.

## Non-Goals (initial version)
- Operating two independent Mem0 services.
- Complex learned retrieval policies before baseline metrics.
- Full ontology management system.

## Acceptance Criteria
- Type-aware metadata on all new writes.
- Intent router controls retrieval composition.
- Context includes episodic/reflection only when policy says so.
- Evaluation shows measurable gains on precision/noise without recall regression.

## Next Engineering Step
Implement Phase 1-3 in one PR-sized change:
1. instrumentation,
2. metadata enforcement,
3. deterministic write classification + dual-write.
