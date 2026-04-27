Update memory files based on the analysis below.
- [FILE] entries: add the described content to the appropriate file
- [FILE-REMOVE] entries: delete the corresponding content from memory files
- [SKILL] entries: create a new skill under skills/<name>/ using **`manage_skill`** (operation **`create`**) with full `SKILL.md` content, or fall back to **`write_file`** on skills/<name>/SKILL.md

## File paths (relative to workspace root)
- SOUL.md
- USER.md
- memory/MEMORY.md
- skills/<name>/SKILL.md (for [SKILL] entries only)

Do NOT guess paths.

## Editing rules
- Edit directly — file contents provided below, no read_file needed
- Use exact text as old_text, include surrounding blank lines for unique match
- Batch changes to the same file into one edit_file call
- For deletions: section header + all bullets as old_text, new_text empty
- Surgical edits only — never rewrite entire files
- If nothing to update, stop without calling tools

## Skill creation rules (for [SKILL] entries)
- Prefer **`manage_skill`** with operation **`create`** (parameters **`name`** + **`content`**). `write_file` under `skills/` remains allowed if needed.
- Before writing, load format reference via **`manage_skill`** operation **`get`** and **`name`** **`skill-creator`**, or **`read_file`** `{{ skill_creator_path }}`
- **Dedup check**: use **`manage_skill`** operation **`list`** (and existing skills below) to avoid redundant skills. Skip creation if one already covers the workflow.
- Include YAML frontmatter with name and description fields
- Keep SKILL.md under 2000 words — concise and actionable
- Include: when to use, steps, output format, at least one example
- Do NOT overwrite existing skills — skip if the skill directory already exists
- Reference specific tools the agent has access to (manage_skill, read_file, write_file, exec, web_search, etc.)
- Skills are instruction sets, not code — do not include implementation code

## Quality
- Every line must carry standalone value
- Concise bullets under clear headers
- When reducing (not deleting): keep essential facts, drop verbose details
- If uncertain whether to delete, keep but add "(verify currency)"
