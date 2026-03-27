# Phase 4: Prompt Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inject the new prompt templates (reasoning protocol, tool guide, self-check) into the system prompt, and update tool descriptions with purpose and anti-patterns.

**Architecture:** Modify the existing `ContextBuilder.build_system_prompt()` to include the new sections in the correct order. The full ContextContributor protocol refactor is deferred — the existing builder is 355 LOC and works. Adding 3 sections to it is simpler and lower-risk than a full architectural refactor.

**Tech Stack:** Python 3.10+, ruff, mypy, pytest

**Spec:** `docs/superpowers/specs/2026-03-27-agent-cognitive-redesign.md`, Phase 4

---

## Tasks

### Task 1: Inject reasoning protocol and tool guide into system prompt

**Files:**
- Modify: `nanobot/context/context.py`

Add the reasoning.md and tool_guide.md templates to `build_system_prompt()`, inserted after identity and before bootstrap files. The new prompt order:

1. Identity (existing)
2. **Reasoning Protocol (NEW)** — `prompts.get("reasoning")`
3. **Tool Guide (NEW)** — `prompts.get("tool_guide")`
4. Bootstrap files (existing)
5. Memory context (existing)
6. Feedback (existing)
7. Active skills (existing)
8. Skills summary (existing)
9. **Self-Check (NEW, conditional)** — `prompts.get("self_check")` if verify_before_answer
10. Security advisory (existing)
11. Unavailable tools (existing)
12. Known contacts (existing)

The templates already exist (created in Phase 2). Just load and inject them.

Also: replace the `verification_required` prompt in `build_messages()` with `self_check`.

### Task 2: Update tool descriptions with purpose and anti-patterns

**Files:**
- Modify: `nanobot/tools/setup.py` (or wherever tools are registered)

Update description strings for key tools:
- `exec` → add "Use for skill commands, system operations, or as a fallback"
- `list_dir` → add "Prefer over search when looking for something by project code or folder name"
- `read_file` → add "If you don't know the path, use list_dir first to find it"

### Task 3: Tests and validation

Write a test verifying the new sections appear in the system prompt in the correct order.
Run `make pre-push` with clean mypy cache.

---

## Summary

| Task | Files Changed | Estimated Effort |
|------|--------------|-----------------|
| 1. Inject new prompts | 1 modified | 15 min |
| 2. Update tool descriptions | 1 modified | 10 min |
| 3. Tests + validation | 1 created/modified | 15 min |
| **Total** | **3 files** | **~40 min** |
