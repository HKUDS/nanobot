# Prompt Consolidation: Migrate Inline Prompts to `prompt_loader`

**Date:** 2026-03-21
**Status:** Draft
**Scope:** Migrate ~29 inline prompt strings to managed `.md` template files,
add template rendering to `prompt_loader`, fix 4 prompt contradictions

## Problem

Only 7 of ~36 prompts in the codebase go through the `prompt_loader` system.
The remaining ~29 are inline Python strings scattered across 10+ modules.
This means:

1. **No CI hash-checking** — unintentional prompt changes go undetected
2. **Hard to review** — prompts are buried in Python logic, not readable as prose
3. **Not user-overridable** — only the 7 managed prompts can be customized via
   the workspace `prompts/` directory
4. **Cross-prompt contradictions** — discovered during audit (see Contradiction
   Resolution section)

## Approach

### 1. Add template rendering to `PromptLoader`

Extend the existing `PromptLoader` with a `render()` method that substitutes
`{variable}` placeholders using `str.format_map()` with a `defaultdict` that
leaves unknown placeholders untouched.

```python
# Existing API (unchanged)
prompts.get("plan")  # returns raw template text

# New API
prompts.render("identity", workspace_path="/home/user/workspace")
# returns text with {workspace_path} substituted, unknown {vars} left as-is
```

Implementation uses `str.format_map()` with a custom `__missing__` dict subclass
that reconstructs `{key}` for unknown placeholders — no new dependencies, no
template engine. Rendered results are NOT cached (templates are small and
rendering is cheap; caching by name+kwargs would add complexity for no gain).

### 2. Migrate inline prompts to `.md` files

Move static and template prompts to `nanobot/templates/prompts/`. Each becomes
a `.md` file, hash-checked by CI, user-overridable via workspace `prompts/`.

### 3. Fix discovered contradictions

Four prompt contradictions are fixed during migration (see section below).
A fifth (delegation trigger architecture) is deferred to a separate analysis
(`docs/contradiction-5-delegation-triggers.md`).

## New Prompt Files

### From `context.py` (6 files)

| File | Variables | Purpose |
|------|-----------|---------|
| `identity.md` | `{runtime}`, `{workspace_path}` | Core agent persona, workspace info, tool guidelines, memory/feedback instructions |
| `memory_header.md` | `{memory}` | Memory section preamble + retrieved memory content |
| `skills_header.md` | `{skills_summary}` | Skills section explaining how to load skills |
| `security_advisory.md` | none | Security rules for untrusted `<tool_result>` content |
| `unavailable_tools.md` | `{unavail}` | List of registered but unavailable tools |
| `verification_required.md` | none | Suffix for turns requiring claim verification |

### From `coordinator.py` (5 files)

| File | Variables | Purpose |
|------|-----------|---------|
| `role_code.md` | none | Code role system prompt |
| `role_research.md` | none | Research role system prompt |
| `role_writing.md` | none | Writing role system prompt |
| `role_system.md` | none | Systems/DevOps role system prompt |
| `role_pm.md` | none | PM/orchestration role system prompt |

### From `loop.py` (8 files)

| File | Variables | Purpose |
|------|-----------|---------|
| `nudge_delegation_exhausted.md` | none | Stop delegating, synthesize and answer |
| `nudge_post_delegation.md` | none | Review delegation results, produce answer |
| `nudge_ungrounded_warning.md` | none | Warning about specialists that skipped tools |
| `nudge_use_parallel.md` | none | Switch from sequential to parallel delegation |
| `nudge_parallel_structure.md` | none | Use delegate_parallel for independent sub-tasks |
| `nudge_plan_enforcement.md` | none | Outline plan before acting |
| `nudge_malformed_fallback.md` | none | Produce answer directly after malformed calls |
| `nudge_final_answer.md` | none | Produce final answer after tool use |

### From `delegation.py` (2 files)

| File | Variables | Purpose |
|------|-----------|---------|
| `delegation_schema.md` | `{evidence_type}` | Required response structure for delegated agents |
| `delegation_agent.md` | `{role_name}`, `{role_prompt}`, `{avail_tools}`, `{output_schema}` | System prompt for delegated specialist agents |

### From `verifier.py` (2 files)

| File | Variables | Purpose |
|------|-----------|---------|
| `recovery.md` | none | Recovery attempt when main loop produces no response |
| `revision_request.md` | `{issue_text}` | Self-check revision with identified issues |

### From subsystems (5 files)

| File | Variables | Purpose |
|------|-----------|---------|
| `consolidation.md` | none | Memory consolidation agent system prompt |
| `extractor.md` | none | Structured memory extractor system prompt |
| `summary_system.md` | none | Tool-output summarizer system prompt |
| `slide_analysis.md` | none | Per-slide PowerPoint analysis prompt |
| `deck_synthesis.md` | none | Deck-level PowerPoint synthesis prompt |
| `heartbeat.md` | none | Heartbeat agent system prompt |

**Total: 29 new `.md` files** (added to the existing 7, bringing the total to 36).

## Prompts That Stay Inline (7)

These remain as inline f-strings because they are trivially dynamic (1-line
templates with runtime values) or heavily computed:

| Prompt | Location | Reason |
|--------|----------|--------|
| `_build_failure_prompt()` | `failure.py:192-228` | Loop-built per-failure-class sections |
| Tool removed nudge | `loop.py:773-778` | 1-line, `{tool_name}`, `{reason}` |
| Repeated-failure warn | `loop.py:783-789` | 1-line, `{tool_name}`, `{count}` |
| Budget exhausted | `loop.py:801-807` | 1-line, `{failure_count}` |
| Too many solo calls | `loop.py:912-918` | 1-line, `{call_count}` |
| Wall-time limit | `loop.py:1036-1039` | 1-line, `{seconds}` |
| Runtime context | `context.py:602-610` | Per-message injection, not a prompt |

## Contradiction Fixes (included in migration)

### Fix 1: Delegation priority ordering

**Problem:** `nudge_delegation_exhausted.md` says "do NOT delegate" while the
solo-call nudge (inline) says "delegate NOW". Both can fire in the same turn.

**Fix:** Add to `nudge_delegation_exhausted.md`:
> "This overrides any earlier instruction to delegate. Budget is exhausted."

Add to the inline solo-call nudge: "unless delegation budget is exhausted."

### Fix 2: Compress preserves delegation structure

**Problem:** When a delegated agent's structured response (Findings/Evidence/
Confidence) is compressed, the section headings are stripped. The main agent
then can't find expected structure, potentially triggering false "ungrounded
results" warnings.

**Fix:** Add to `compress.md`:
> "When compressing delegation results, preserve section headings (Findings,
> Evidence, Confidence) even if you shorten their content."

### Fix 3: "Never predict results" vs. planning

**Problem:** `identity.md` says "NEVER predict or describe the expected result"
but `plan.md` encourages multi-step plans that inherently describe what tools
will do.

**Fix:** Clarify in `identity.md`:
> "Before calling tools, you may briefly state your intent (e.g. 'Let me check
> that'), but do not describe what you expect the tool to return."

### Fix 4: `{key}` placeholder in `summary_system.md`

**Problem:** The `_SUMMARY_SYSTEM` prompt contains literal `{key}` intended for
the LLM to fill in, but `str.format_map()` would try to substitute it.

**Fix:** Escape as `{{key}}` in the `.md` file. Add an inline comment:
`<!-- {{key}} is an LLM-facing placeholder, not a Python variable -->`

### Deferred: Contradiction 5 (delegation trigger architecture)

Three independent mechanisms trigger delegation (classifier, planner, runtime
counter) with no priority ordering. This is an architectural issue requiring
separate analysis. Report written to `docs/contradiction-5-delegation-triggers.md`.

## Changes to Production Code

### `prompt_loader.py`

- Add `render(name: str, **kwargs) -> str` method
- Uses `str.format_map()` with a `defaultdict` for safe partial rendering
- `get()` remains unchanged (backward compatible)

### `context.py`

- Replace inline strings with `prompts.get()` / `prompts.render()` calls
- `_get_identity()` becomes `prompts.render("identity", ...)`
- Section builders use `prompts.get()` for static sections

### `coordinator.py`

- `DEFAULT_ROLES` system_prompt fields become `prompts.get("role_code")` etc.
- **Must use lazy loading** (e.g. inside `Coordinator.__init__` or a factory
  function), NOT module-level init — `PromptLoader._workspace` is not set until
  `AgentLoop.__init__` runs, so module-level `prompts.get()` would silently
  skip workspace overrides

### `loop.py`

- Replace 8 static nudge strings with `prompts.get("nudge_*")` calls
- 5 dynamic nudges stay inline (tool removed, repeated failure, budget, solo
  calls, wall-time)

### `delegation.py`

- `delegation_schema` and agent system prompt use `prompts.render()`

### `verifier.py`

- Recovery prompt and revision request use `prompts.get()` / `prompts.render()`

### `memory/store.py`, `memory/extractor.py`

- System prompts become `prompts.get("consolidation")`, `prompts.get("extractor")`

### `tools/result_cache.py`, `tools/powerpoint.py`

- Module-level constants become `prompts.get()` calls (lazy-loaded on first use)

### `heartbeat/service.py`

- System prompt becomes `prompts.get("heartbeat")`

### `scripts/check_prompt_manifest.py`

- No changes needed — already scans all `.md` files in the prompts directory

### `prompts_manifest.json`

- Regenerated via `python scripts/check_prompt_manifest.py --update` after all
  files are created

## Testing

- Existing `prompt_loader` tests extended for `render()` method
- `render()` with known variables substitutes correctly
- `render()` with unknown variables leaves them untouched
- `render()` with no variables behaves like `get()`
- `check_prompt_manifest.py --update` succeeds with new files
- `make check` passes (all existing tests + new prompt tests)
- No behavioral changes — all prompts produce identical text to current inline
  versions (except the 4 contradiction fixes)

## Out of Scope

- Contradiction 5 (delegation trigger architecture) — separate report
- User-facing documentation for overridable prompts
- A/B testing or prompt versioning infrastructure
- Changes to the `failure.py` dynamic prompt builder
