Update memory files based on the analysis below.

## Quality standards
- Every line must carry standalone value — no filler
- Concise bullet points under clear headers
- Remove outdated, contradicted, or completed information

## Cleanup rules
When you see [FILE-REMOVE] entries or detect stale content:
- DELETE entire sections for completed one-time events (triage, one-time reviews, research projects)
- DELETE individual bullets for resolved tracking items (merged/closed PRs, fixed issues)
- REDUCE detailed incident/attack info to one-line summaries after 14 days
- CONSOLIDATE: merge 3+ similar entries into one concise summary
- KEEP: ongoing situations, long-term preferences, unresolved issues, project conventions
- If uncertain whether to delete, keep but add "(verify currency)" note

## File paths — CRITICAL
The memory files are located at these EXACT paths (relative to workspace root):
- SOUL.md (workspace root)
- USER.md (workspace root)
- memory/MEMORY.md (inside the "memory" subdirectory)

Do NOT use any other paths. Do NOT guess paths.

## Editing
- File contents provided below — edit directly, no read_file needed
- Use exact text from the file content below as old_text for replacements
- Include surrounding blank lines in old_string to ensure unique match
- Batch changes to the same file into one edit_file call
- For large deletions: include the full section header + all bullets as old_string, set new_string to empty string
- Surgical edits only — never rewrite entire files
- Do NOT overwrite correct entries — only add, update, or remove
- If nothing to update, stop without calling tools
