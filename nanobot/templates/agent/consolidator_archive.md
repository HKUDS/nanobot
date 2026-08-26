Create a memory overview for only the final {{ archive_count }} conversation messages immediately before this instruction. Earlier messages are context for resolving references; do not summarize them again.

Use [skip] unless a fact meets all SNIP criteria:
- Signal: would the user need to repeat this if forgotten?
- Novel: not just a restatement of another fact in this same conversation chunk
- Important: prevents rework or captures preferences / rules
- Persistent: still relevant after 2 weeks

Format each fact as:
- [mark] fact content

Marks (choose the best match):
- [permanent] Core preferences, personal traits, habits — never becomes stale
- [durable] Technical discoveries, project knowledge, config details — valid for months
- [ephemeral] Active task state, temporary decisions — may change in weeks
- [correction] Correction to a previous memory — state what changed
- [skip] Conversational filler, code/source facts derivable from the repo, or audit-only breadcrumbs

Priority: user corrections and preferences > solutions > decisions > events > environment facts.

Do not output facts already present in the system prompt's Recent History.

Do not mark something [skip] merely because it might already exist in long-term memory.

Return only formatted fact lines, or `(nothing)` if nothing noteworthy happened.
