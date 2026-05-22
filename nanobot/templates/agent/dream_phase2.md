Update memory files based on the analysis below.
- [FILE] entries: add the described content to the appropriate file (use the →TARGET routing)
- [FILE-REMOVE] entries: delete the corresponding content from memory files
  - To remove a line: use apply_patch Update File with the exact line prefixed by `-`
  - To remove an entire file: use apply_patch Delete File
- [SKILL] entries: create a new skill under skills/<name>/SKILL.md using write_file

## Routing rules (→TARGET tells you which file)
- →USER → write to USER.md
- →SOUL → write to SOUL.md
- →MEMORY → write to memory/MEMORY.md
- No target specified → default to memory/MEMORY.md

## File paths (relative to workspace root)
- SOUL.md
- USER.md
- memory/MEMORY.md
- skills/<name>/SKILL.md (for [SKILL] entries only)

Do NOT guess paths.

## Editing rules
- Default tool for edits: apply_patch. Use edit_file only for small exact replacements.
- File contents are provided below — no read_file needed for editing.
- Batch all changes (across files) into a single apply_patch call.
- Surgical edits only — never rewrite entire files unless necessary.
- Set dry_run=true to preview changes before writing.
- If nothing to update, stop without calling tools.

## MECE enforcement
- USER.md: personal info, preferences, habits, work context — no technical configs
- SOUL.md: agent behavior rules, guardrails, communication patterns — no user facts
- MEMORY.md: technical knowledge, project context, infrastructure — no user preferences
- If a fact belongs in multiple files, keep it in the most specific one and remove from others

## Skill creation rules (for [SKILL] entries)
- Use write_file to create skills/<name>/SKILL.md
- Before writing, read_file `{{ skill_creator_path }}` for format reference (frontmatter structure, naming conventions, quality standards)
- **Dedup check**: read existing skills listed below to verify the new skill is not functionally redundant. Skip creation if an existing skill already covers the same workflow.
- Include YAML frontmatter with name and description fields
- Keep SKILL.md under 2000 words — concise and actionable
- Include: when to use, steps, output format, at least one example
- Do NOT overwrite existing skills — skip if the skill directory already exists
- **Skill-to-skill MECE**: if a new skill overlaps with an existing skill, merge the delta into the existing skill via edit_file instead of creating a redundant one
- Reference specific tools the agent has access to (read_file, write_file, exec, web_search, etc.)
- Skills are instruction sets, not code — do not include implementation code

## Skill vs MEMORY.md boundary
- SKILL.md = reusable workflow template (steps, syntax reminders, output format, examples)
- MEMORY.md = concrete config values, credentials, paths, infrastructure details
- Keep concrete values in MEMORY.md; skill should use placeholders or reference MEMORY.md entries
- Do not let technical configs leak into skills, do not let workflow steps leak into MEMORY.md

## Quality
- Every line must carry standalone value
- Concise bullets under clear headers
- When reducing (not deleting): keep essential facts, drop verbose details
- If uncertain whether to delete, keep but add "(verify currency)"
- Do NOT include the →TARGET or #DECAY tags in the actual file content — they are metadata for routing only
