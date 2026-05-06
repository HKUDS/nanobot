Create a compact session handoff for future resume.

Capture only the highest-value carry-forward state from this conversation:
- Objective: the current goal or task
- Decisions: concrete choices already made
- Constraints: limits, preferences, or guardrails that affect next steps
- Next step: the most likely immediate follow-up action
- Blockers: open problems or missing prerequisites
- Key refs: only essential file paths, branch names, commands, ids, or services

Rules:
- Keep it very short and dense.
- Prefer stable resume context over narration.
- Do not repeat low-value chatter, obvious code facts, or generic status.
- Omit anything derivable directly from source unless it is necessary to resume work correctly.
- If a section has nothing useful, omit it.
- If there is nothing worth carrying forward, output: (nothing)

Output format:
- One bullet per fact.
- Start each bullet with exactly one of: Objective:, Decision:, Constraint:, Next:, Blocker:, Ref:
- No preamble. No commentary.
- Keep the whole output compact.
