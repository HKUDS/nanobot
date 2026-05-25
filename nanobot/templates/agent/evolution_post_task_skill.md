Write a complete SKILL.md for a new agent skill based on the completed turn below.

Output the full SKILL.md markdown only (no JSON wrapper). Start with YAML frontmatter:

---
name: {{ skill_name }}
description: One-line description for skill routing
---

Rules:
- Keep the body under 2000 words — concise and actionable
- Include: when to use, step-by-step workflow, output format, at least one example
- Reference tools the agent has (read_file, write_file, exec, web_search, etc.) where relevant
- Skills are instruction sets, not code — do not include implementation code
- Do not duplicate an existing workspace skill (see list below)

Proposed skill name: {{ skill_name }}
Rationale: {{ rationale }}

User query:
{{ query }}

Skills already injected this turn:
{{ skills_injected }}

Tool calls:
{{ tool_calls }}

Existing workspace skills (dedup — do not recreate the same workflow):
{{ existing_skills }}
