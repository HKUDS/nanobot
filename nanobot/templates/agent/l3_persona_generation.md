Synthesize a durable **user persona** for ``USER.md`` from L1 atoms and L2 scene documents.

Reply with **JSON only** in this exact shape:
```json
{
  "action": "update|skip",
  "content_md": "# User Profile\n..."
}
```

Rules:
- Output **stable, cross-session** preferences: language, communication style, standing rules, work context
- Use **update** when scenes/atoms add or refine durable user traits; **skip** when nothing new
- ``content_md`` is the **full** updated ``USER.md`` (Markdown with clear headers)
- Preserve still-valid facts from the current profile; merge, do not blindly wipe
- Do **not** duplicate transient task steps, tool output, or per-project detail better left in L2 scenes
- Do **not** write skills, SOPs, or bot personality (SOUL.md is separate)
- Keep under {{ max_user_chars }} characters; prefer concise bullets
- If current profile is empty, create a minimal structured profile from scenes/atoms

Session that triggered this job: {{ session_key }}

Current USER.md:
{{ current_user }}

Scene index:
{{ scene_index }}

Scene bodies (summaries):
{{ scene_bodies }}

Recent L1 atoms (workspace-wide):
{{ atoms }}
