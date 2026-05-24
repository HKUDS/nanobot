Select skills that are relevant to the user message.

Reply with JSON only in this exact shape:
{"skills": ["skill_name", "..."]}

Rules:
- Choose only from the candidate list below
- Select at most {{ max_k }} skills
- If none are relevant, return {"skills": []}
- Use exact candidate names from the list

User message:
{{ query }}

Candidates:
{{ candidates }}
