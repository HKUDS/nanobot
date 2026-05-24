Review the completed agent turn below and decide whether to create a new workspace skill.

Reply with JSON only in this exact shape:
{"action": "none" | "create_skill", "skill_name": "kebab-case-name", "rationale": "...", "confidence": 0.0}

Rules:
- Only propose **create_skill** when the turn shows repeatable procedural knowledge worth capturing
- Use action **none** when the task was one-off, trivial, or already covered by existing skills
- **Never** propose updating an existing skill — updates are handled offline by GEPA
- skill_name must be kebab-case (lowercase letters, digits, hyphens)
- confidence is 0.0–1.0; use high confidence only when creation is clearly justified

User query:
{{ query }}

Skills already injected this turn:
{{ skills_injected }}

Tool calls ({{ tool_call_count }} total, {{ iterations }} iteration(s)):
{{ tool_calls }}
