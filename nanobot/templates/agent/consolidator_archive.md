Create a memory overview for only the final {{ archive_count }} conversation messages immediately before this instruction. Earlier messages are context for resolving references; do not summarize them again.

Do not call tools. Return only the overview, following these memory rules:

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

Do not output facts already present in the system prompt's Recent History.

Do not mark something [skip] merely because it might already exist in long-term memory; Dream handles cross-file deduplication later.

Output concise bullet points only. No preamble, no commentary.
If nothing noteworthy happened, output: (nothing)
