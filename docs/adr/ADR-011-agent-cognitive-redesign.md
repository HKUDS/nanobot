# ADR-011: Agent Cognitive Core Redesign

**Status:** Accepted
**Date:** 2026-03-27
**Deciders:** Project owner + Claude Opus 4.6

## Context

Exhaustive analysis of 13 Langfuse traces revealed the agent repeatedly
failed at a simple Obsidian folder lookup task. Root cause: architecture
invested in orchestration complexity instead of reasoning quality.

The PAOR (Plan-Act-Observe-Reflect) loop comprised TurnOrchestrator,
ActPhase, ReflectPhase, and AnswerVerifier totaling ~1,150 LOC. It
enforced rigid phase transitions that added latency and token cost
without improving task completion. The AnswerVerifier produced false
positives, and the planning phase generated plans the model did not
follow.

## Decision

Replace the PAOR loop with a simple tool-use loop (TurnRunner) with
modular extension points. The architecture has four layers:

### Four-Layer Architecture

```
ENTRY LAYER          MessageProcessor
                     Receives messages, manages sessions, delivers responses

COGNITIVE LOOP       TurnRunner
                     Simple tool-use loop with guardrail checkpoints

GUARDRAIL LAYER      GuardrailChain
                     Modular failure pattern detection (plugin-based)

PROMPT LAYER         ContextBuilder + prompt templates
                     System prompt architecture + tool descriptions + skills
```

### TurnRunner Loop (Pseudocode)

```
while iteration < max_iterations:
    if wall_time_exceeded: break
    if context_over_budget: compress(messages)

    response = call_llm(messages, tools)
    if llm_error: handle_error(); continue

    if response.has_tool_calls:
        results = execute_batch(response.tool_calls)
        add_results_to_messages()
        update_working_memory(results)      # ToolAttempt log

        intervention = guardrail_chain.check(state)
        if intervention: inject(intervention)
        continue

    final_content = response.content
    break

if verification_enabled:
    final_content = self_check(final_content, messages)
```

### Guardrail Layer

Five guardrails in priority order (first intervention wins):

| # | Guardrail | Fires When | Severity |
|---|-----------|-----------|----------|
| 1 | FailureEscalation | Tool fails N times | directive |
| 2 | NoProgressBudget | 4+ iterations with no useful data | override |
| 3 | RepeatedStrategyDetection | Same tool+args 3 times | override |
| 4 | EmptyResultRecovery | Tool succeeds but returns no data | hint/directive |
| 5 | SkillTunnelVision | All exec calls, no data, iteration >= 3 | directive |

Each guardrail is a pure function: receives iteration context, returns
`Intervention | None`. Adding a guardrail = new class + register in factory.
No changes to TurnRunner or other guardrails.

### Three-Tier Memory

| Tier | Scope | Content | Storage |
|------|-------|---------|---------|
| Declarative | Cross-session | Facts, entities | SQLite (existing) |
| Procedural | Cross-session | Tool strategies (what worked/failed) | SQLite (strategies table) |
| Working | Per-turn | ToolAttempt log for guardrail reasoning | In-memory TurnState |

### Feedback Loop

```
Session 1: Agent fails → guardrail fires → recovery succeeds
           → strategy extracted (confidence 0.5)
Session 2: Strategy in prompt → agent succeeds without guardrail
           → confidence bumped to 0.6
Session 5: Confidence 0.9 → agent handles this permanently
```

### System Prompt Structure (11 sections, strict order)

1. Identity
2. Reasoning Protocol (reasoning.md — pre-action reasoning steps)
3. Tool Guide (tool_guide.md — purpose-driven selection with anti-patterns)
4. Strategies (procedural memory — learned strategies from past sessions)
5. Memory (declarative — facts and entities)
6. Bootstrap Files (workspace: AGENTS.md, SOUL.md, etc.)
7. Feedback (past user corrections)
8. Active Skills (always=true skill content)
9. Skills Summary (on-demand loading)
10. Self-Check (conditional verification instructions)
11. Security Advisory (prompt injection boundary)

### Key Design Decisions

- **Model-agnostic** — works with weak models via structural enforcement
- **Single agent with optional spawning** — no multi-role routing
- **Layered reasoning enforcement** — prompts (proactive) + guardrails (reactive)
- **The loop is dumb, the prompt is smart** — behavioral fixes go through
  extension points (guardrails, prompt templates), not loop conditionals
- **Configurable verification** — prompt-only default, optional structured self-check

### 15 Structural Stability Patterns

1. The Loop Is Dumb, The Prompt Is Smart
2. Guardrails Are Plugins, Not States
3. Context Is Layered and Composable
4. Memory Has Three Tiers
5. Feedback Loops Close the Learning Gap
6. Stable Core / Volatile Edge
7. One File, One Reason to Change
8. Protocols at Boundaries, Concrete Inside
9. Three Extension Points (guardrails, context contributors, prompt templates)
10. Growth Limits (guardrail count ≤ 10, contributors ≤ 15, templates ≤ 100 LOC)
11. Observable by Default
12. No Implicit Coupling
13. Prompt Changes Are Code Changes
14. Design for Deletion
15. Test by Contract, Not Implementation

## Implementation

Executed across 6 phases:

- **Phase 1**: Deleted routing, role-switching, delegation advisor, plan
  enforcement (-5,265 LOC)
- **Phase 2**: Created guardrails, ToolAttempt, Strategy/StrategyStore,
  prompt templates (+481 LOC)
- **Phase 3**: Replaced TurnOrchestrator with TurnRunner (-1,588 LOC)
- **Phase 4**: Injected reasoning protocol and tool guide into system
  prompt (+14 LOC)
- **Phase 5**: Wired procedural memory (StrategyExtractor) into pipeline
  (+460 LOC)
- **Phase 6**: Cleanup — updated docs, removed stale references,
  created this ADR

## Consequences

- Net reduction: ~6,000+ LOC across 6 phases
- New capabilities: guardrails, procedural memory, reasoning protocol
- The loop rarely changes; behavioral fixes go through extension points
- Cross-session learning via procedural memory feedback loop
- Simpler mental model: tool-use loop + guardrails vs. PAOR state machine

## Supersedes

- ADR-002 (Agent Loop Ownership) — loop redesigned from PAOR to
  tool-use loop with guardrails
- TurnOrchestrator + ActPhase + ReflectPhase — replaced by TurnRunner
- AnswerVerifier — replaced by configurable self-check
- Multi-role routing (MessageRouter, TurnRoleManager) — removed entirely
- DelegationAdvisor — removed; delegation via tools only
