Extract key facts from this conversation. For each fact, annotate its memory attributes.

Only SNIP facts deserve a non-[skip] mark:
- Signal: would the user need to repeat this if forgotten?
- Novel: not already in MEMORY.md or USER.md (check context below)
- Important: prevents rework or captures preferences / rules
- Persistent: still relevant after 2 weeks

Output one fact per line in this format:
- [mark] fact content

Marks (choose the best match):
- [permanent] Core preferences, personal traits, habits — never becomes stale
- [durable] Technical discoveries, project knowledge, config details — valid for months
- [ephemeral] Active task state, temporary decisions — may change in weeks
- [correction] Correction to a previous memory — must state what it replaces
- [skip] Does not meet SNIP criteria — still written to history.jsonl for audit, but Dream will ignore it

Categories to capture: people/roles, decisions/rationale, solutions, events/dates, preferences.
Decisions must include their motivation.
Write densely. Prefer 'X=A, Y=B' over separate bullets for tightly coupled facts.
Priority: user corrections > decisions with rationale > solutions > specific events > general context.
Output in the same language as the input conversation.
CRITICAL: Never drop person names, team names, or project names.
Skip: code patterns derivable from source, git history, or anything already in existing memory.

If nothing noteworthy happened, output: (nothing)
