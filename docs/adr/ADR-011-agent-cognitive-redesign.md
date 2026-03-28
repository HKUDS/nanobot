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

Replace the PAOR loop with a simple tool-use loop (TurnRunner, ~573 LOC)
with modular extension points:

1. **Guardrail checkpoints** (GuardrailChain) -- modular failure pattern
   detection that fires between tool-use iterations. Each guardrail
   inspects ToolAttempt history and can inject recovery prompts or
   disable failing tools.

2. **Working memory** (ToolAttempt) -- structured log of every tool call
   with name, arguments, result summary, duration, and success flag.
   Guardrails read this to detect patterns (e.g., repeated failures,
   looping on the same file).

3. **Procedural memory** (StrategyExtractor + StrategyStore) -- learned
   strategies extracted from guardrail recovery events and persisted
   across sessions. On future tasks, matching strategies are injected
   into the system prompt.

4. **Configurable self-check** -- replaces the separate AnswerVerifier
   with an optional in-loop self-check pass controlled by agent config.
   Uses the same model, no separate LLM call unless configured.

5. **Reasoning protocol** -- structured prompt template (reasoning.md)
   injected into the system prompt, guiding the model through pre-action
   reasoning without enforcing rigid phase transitions.

6. **Tool guide** -- purpose-driven tool selection prompt (tool_guide.md)
   with anti-patterns, injected into the system prompt to prevent common
   tool misuse.

Key design decisions:
- Model-agnostic (works with weak models via structural enforcement)
- Single agent with optional spawning (no multi-role routing)
- Layered reasoning enforcement (prompts + guardrails)
- The loop is a dumb tool-use driver; behavioral fixes go through
  extension points (guardrails, context contributors, prompt templates)

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
- **Phase 6**: Cleanup -- updated docs, removed stale references,
  created this ADR

## Consequences

- Net reduction: ~6,000+ LOC across 6 phases
- New capabilities: guardrails, procedural memory, reasoning protocol
- The loop rarely changes; behavioral fixes go through extension points
  (guardrails, context contributors, prompt templates)
- Cross-session learning via procedural memory feedback loop
- Simpler mental model: tool-use loop + guardrails vs. PAOR state machine

## Supersedes

- ADR-002 (Agent Loop Ownership) -- loop redesigned from PAOR to
  tool-use loop with guardrails
- TurnOrchestrator + ActPhase + ReflectPhase -- replaced by TurnRunner
- AnswerVerifier -- replaced by configurable self-check
- Multi-role routing (MessageRouter, TurnRoleManager) -- removed entirely
- DelegationAdvisor -- removed; delegation via tools only
