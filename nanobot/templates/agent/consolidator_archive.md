Extract key facts from this conversation. For each fact, annotate its memory attributes.

Only SNIP facts deserve a non-[skip] mark:
- Signal: would the user need to repeat this if forgotten?
- Novel: not just a restatement of another fact in this same conversation chunk
- Important: prevents rework or captures preferences / rules
- Persistent: still relevant after 2 weeks

Output one fact per line in this format:
- [mark] fact content

Marks (choose the best match):
- [permanent] Core preferences, personal traits, habits — never becomes stale
- [durable] Technical discoveries, project knowledge, config details — valid for months
- [ephemeral] Active task state, temporary decisions — may change in weeks
- [correction] Correction to a previous memory — state what changed
- [skip] Does not meet SNIP criteria, is conversational filler, is code/source facts derivable from the repo, or is only useful as an audit breadcrumb

Priority: user corrections and preferences > solutions > decisions > events > environment facts. The most valuable memory prevents the user from having to repeat themselves.

Source discipline:
- Facts stated or explicitly confirmed by the user may receive [permanent], [durable], [ephemeral], or [correction].
- Tool outputs and source-code observations may receive [durable] when they are concrete project facts, not agent speculation.
- Agent-only guesses, inferred preferences, proposed options, and interpretations that the user did not confirm must be [skip], or [ephemeral] only when needed to resume the active task and marked "(agent-inferred)".
- If a Current long-term memory excerpt is provided, mark facts already captured there as [skip] unless the conversation corrects, narrows, or supersedes them.
- Preserve the narrowest true scope. Do not broaden a project-specific or task-specific observation into a global user preference.

Output concise bullet points only. No preamble, no commentary.
If nothing noteworthy happened, output: (nothing)
