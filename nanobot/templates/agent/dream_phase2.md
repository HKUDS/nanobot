Apply the structured updates from the analysis below.

Allowed paths:
- SOUL.md
- USER.md
- memory/MEMORY.md
- skills/<name>/SKILL.md (for [SKILL] creation only)

## Editing rules
- Use edit_file with exact old_text/new_text
- Batch changes to the same file into one edit_file call
- For deletions: section header + all bullets as old_text, new_text empty
- Surgical edits only — never rewrite entire files
- If the updates array is empty, stop without calling tools

## Skill creation rules (for create action on skills/<name>/SKILL.md)
- Use write_file to create the file
- Before writing, read_file `{{ skill_creator_path }}` for format reference (frontmatter structure, naming conventions, quality standards)
- **Dedup check**: read existing skills listed below to verify the new skill is not functionally redundant. Skip creation if an existing skill already covers the same workflow.
- Include YAML frontmatter with name and description fields
- Keep under 2000 words — concise and actionable
- Do NOT overwrite existing skills
- Skills are instruction sets — do not include implementation code

## Quality
- Every line must carry standalone value
- Concise bullets under clear headers
- When reducing (not deleting): keep essential facts, drop verbose details
- If uncertain whether to delete, keep but add "(verify currency)"
