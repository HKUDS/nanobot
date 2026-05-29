Synthesize durable **scenario documents** from L1 memory atoms for this session.

Reply with **JSON only** in this exact shape:
```json
{
  "scenes": [
    {
      "action": "create|update|skip",
      "slug": "kebab-case-topic",
      "title": "Human-readable scene title",
      "summary": "One-line synopsis (≤ 120 chars).",
      "content_md": "# Title\\n\\n## Summary\\n...",
      "source_atom_ids": ["l1_abc123"]
    }
  ]
}
```

Rules:
- Group related atoms into **one ongoing topic** (project, workflow, recurring task)
- Use **create** for a new scene file; **update** to revise an existing scene (output the **full** updated markdown)
- Use **skip** when atoms are too sparse or already covered with nothing new to add
- ``slug`` must be lowercase kebab-case (letters, digits, hyphens)
- ``content_md`` is Markdown: ``# Title``, ``## Summary``, ``## Key facts``, ``## Rules / preferences``, ``## Timeline`` as needed
- Reference ``source_atom_ids`` from the atom list when possible
- **Do not** write skills, SOPs, or executable procedures
- Prefer **one** scene per response unless two clearly separate topics exist
- If nothing deserves a scene, return ``{"scenes": [{"action": "skip"}]}``

Session: {{ session_key }}

Existing scenes (index):
{{ existing_scenes }}

L1 atoms for this session:
{{ atoms }}
