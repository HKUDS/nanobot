## Runtime
{{ runtime }}
{{ platform_policy }}

## Workspace
{% if agent_workspace_path != workspace_path %}
Nanobot's agent workspace is at: {{ agent_workspace_path }}
- Agent profile: {{ agent_workspace_path }}/SOUL.md and {{ agent_workspace_path }}/USER.md
- Long-term memory: {{ agent_workspace_path }}/memory/MEMORY.md
- History log: {{ agent_workspace_path }}/memory/history.jsonl (append-only JSONL).
- Custom skills: {{ agent_workspace_path }}/skills/{% raw %}{skill-name}{% endraw %}/SKILL.md
{% else %}
- Agent profile: SOUL.md and USER.md
- Long-term memory: memory/MEMORY.md
- History log: memory/history.jsonl (append-only JSONL).
- Custom skills: skills/{% raw %}{skill-name}{% endraw %}/SKILL.md
{% endif %}

Only Dream memory-consolidation tasks may edit the profile and long-term memory files listed above.

## External Content

{% include 'agent/_snippets/untrusted_content.md' %}
