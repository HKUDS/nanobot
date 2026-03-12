# ADR-008: Prompt Management

## Status

Accepted

## Date

2026-03-12

## Context

Prior to Phase 2, all system prompts were Python string constants embedded
directly in `loop.py`.  This made prompts hard to review, edit, and A/B test
without touching Python code.  The file was 2,500+ lines partly due to large
multi-line prompt strings.

## Decision

1. **Externalize prompts to Markdown files** in `nanobot/templates/prompts/`:

   | File | Purpose |
   |------|---------|
   | `system.md` | Core identity and behavioral rules |
   | `plan.md` | Planning phase instruction |
   | `reflect.md` | Reflection/recovery on tool failure |
   | `verify.md` | Self-critique verification pass |
   | `final_answer.md` | Nudge the LLM toward a final response |
   | `delegation.md` | Delegation contract for sub-agents |
   | `tool_error.md` | Tool execution failure summary |

2. **`PromptLoader`** (`nanobot/agent/prompt_loader.py`) loads all `.md` files
   from the templates directory at import time.  A module-level `prompts`
   dict provides dict-like access: `prompts["plan"]`, `prompts.get("verify")`.

3. **No templating engine.** Prompts are plain Markdown.  Dynamic values
   (tool names, context snippets) are injected via Python string formatting
   at the call site in `loop.py`.

4. **Prompt files are static assets** shipped with the package.  They are NOT
   user-editable at runtime — user customization goes into `SOUL.md` and
   skill files.

## Consequences

### Positive

- Prompts can be reviewed and edited without navigating Python code.
- Smaller `loop.py` — reduced from ~2,500 to ~1,830 lines.
- Prompt changes show up as clean Markdown diffs in PRs.
- `PromptLoader` is independently testable.

### Negative

- One more layer of indirection: prompt text lives in files, not inline.
- No template variable validation — format string mismatches fail at runtime.

### Neutral

- `prompts` dict is read-only after module import.
- Prompt file additions require no code changes to the loader.
