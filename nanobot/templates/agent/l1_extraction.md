Review the conversation transcript below and extract durable memory atoms for long-term recall.

Reply with **JSON only** in this exact shape:
```json
{
  "atoms": [
    {
      "type": "preference|fact|event|rule",
      "content": "One concise standalone sentence.",
      "source_turn_ids": ["turn-id-from-transcript"]
    }
  ]
}
```

Rules:
- Extract only **stable, user-specific** information worth recalling in future turns
- **Do not** extract transient task steps, tool output dumps, or assistant boilerplate
- **Never** write skills, SOPs, or executable procedures (those belong in the skill system)
- Use **preference** for likes/dislikes/settings; **fact** for stable user/project facts; **event** for dated happenings; **rule** for standing constraints the user stated
- Each ``content`` must be self-contained (≤ 200 chars); skip vague or duplicate atoms
- ``source_turn_ids`` should reference turn headers from the transcript when known; may be empty
- If nothing is worth storing, return ``{"atoms": []}``

Conversation (session: {{ session_key }}, turns: {{ turn_count }}):
{{ dialogue }}
