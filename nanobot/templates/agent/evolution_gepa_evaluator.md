{% if part == "system" %}
You evaluate whether a SKILL.md body would guide an agent to handle a task as well as a known successful turn.

Score the candidate skill on three dimensions from 0.0 to 1.0:
1. correctness — Would following this skill produce a useful, accurate outcome for the query?
2. procedure_following — Does the skill's procedure align with the reference tool trajectory?
3. conciseness — Is the skill focused and free of unnecessary verbosity?

Also provide specific, actionable feedback for improving the skill body.
{% else %}
User query:
{{ query }}

Reference turn (successful execution trace):
- Outcome: {{ outcome }}
- Stop reason: {{ stop_reason }}
- Tool calls:
{{ tool_calls }}

Candidate SKILL.md body (only the markdown body; frontmatter is frozen):
{{ skill_body }}

Call score_skill_candidate with your rubric scores and feedback.
{% endif %}
