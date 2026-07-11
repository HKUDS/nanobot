[Subagent '{{ label }}' {{ status_text }}]

Task: {{ task }}

Result:
{{ result }}

Use this result as evidence for the current turn. For MapReduce-style work,
preserve any Summary / Evidence / Open issues structure when reducing multiple
results. Mention gaps or failures if they affect the answer; avoid exposing
internal task IDs unless they are needed for clarity.
