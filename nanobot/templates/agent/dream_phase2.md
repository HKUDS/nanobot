Update memory files based on the analysis below.
- [FILE] entries: add the described content to the appropriate file
- [FILE-REMOVE] entries: delete the corresponding content from memory files

## File paths (relative to workspace root)
- SOUL.md
{% if not skip_user_edits %}- USER.md
{% endif %}- memory/MEMORY.md

{% if skip_user_edits %}
**USER.md** is managed by Layered Memory (L3 persona job). Do **not** edit USER.md in this phase.
{% endif %}

Do NOT guess paths. Do NOT write to `skills/` — skill creation is handled by the evolution system, not Dream.

## Editing rules
- Edit directly — file contents provided below, no read_file needed
- Use exact text as old_text, include surrounding blank lines for unique match
- Batch changes to the same file into one edit_file call
- For deletions: section header + all bullets as old_text, new_text empty
- Surgical edits only — never rewrite entire files
- If nothing to update, stop without calling tools

## Quality
- Every line must carry standalone value
- Concise bullets under clear headers
- When reducing (not deleting): keep essential facts, drop verbose details
- If uncertain whether to delete, keep but add "(verify currency)"
