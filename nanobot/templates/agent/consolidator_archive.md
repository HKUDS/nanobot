Extract key facts from this conversation. For each fact, annotate its memory attributes.

Output one fact per line in this format:
- [mark] fact content

Marks (choose the best match):
- [permanent] Core preferences, personal traits, habits — never becomes stale
- [durable] Technical discoveries, project knowledge, config details — valid for months
- [ephemeral] Active task state, temporary decisions — may change in weeks
- [correction] Correction to a previous memory — must state what it replaces (e.g., "location is Tokyo, not Osaka")
- [skip] Chitchat, debug noise, info already in existing memory — still written to history.jsonl for audit, but Dream will ignore it

Priority: user corrections and preferences > solutions > decisions > events > environment facts.
The most valuable memory prevents the user from having to repeat themselves.

Mark as [skip]:
- Info already captured in existing memory (check the context below)
- Transient debugging, error messages, conversational filler
- Facts derivable from source code or git history

Output as concise bullet points, one fact per line. No preamble, no commentary.
If nothing noteworthy happened, output: (nothing)
