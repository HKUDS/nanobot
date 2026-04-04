Compare conversation history against current memory files.
Output one line per finding:
[FILE] atomic fact or change description

Files: USER (identity, preferences, habits), SOUL (bot behavior, tone), MEMORY (knowledge, project context, tool patterns)

Rules:
- Only new or conflicting information — skip duplicates and ephemera
- Prefer atomic facts: "has a cat named Luna" not "discussed pet care"
- Corrections: [USER] location is Tokyo, not Osaka
- Also capture confirmed approaches: if the user validated a non-obvious choice, note it

If nothing needs updating: [SKIP] no new information
