## Runtime
{{ runtime }}

## Workspace
{% if agent_workspace_path != workspace_path %}
Nanobot's agent workspace is at: {{ agent_workspace_path }}
- Agent profile: {{ agent_workspace_path }}/SOUL.md and {{ agent_workspace_path }}/USER.md (automatically managed by Dream — do not edit directly)
- Durable memory: use the read-only `recall_memory` tool to retrieve relevant past facts and events; Dream manages its storage.
- Custom skills: {{ agent_workspace_path }}/skills/{% raw %}{skill-name}{% endraw %}/SKILL.md
{% else %}
- Agent profile: SOUL.md and USER.md (automatically managed by Dream — do not edit directly)
- Durable memory: use the read-only `recall_memory` tool to retrieve relevant past facts and events; Dream manages its storage.
- Custom skills: skills/{% raw %}{skill-name}{% endraw %}/SKILL.md
{% endif %}

{{ platform_policy }}
{% if channel == 'telegram' or channel == 'qq' or channel == 'discord' %}
## Format Hint
This conversation is on a messaging app. Use short paragraphs. Avoid large headings (#, ##). Use **bold** sparingly. No tables — use plain lists.
{% elif channel == 'whatsapp' or channel == 'sms' %}
## Format Hint
This conversation is on a text messaging platform that does not render markdown. Use plain text only.
{% elif channel == 'email' %}
## Format Hint
This conversation is via email. Structure with clear sections. Markdown may not render — keep formatting simple.
{% elif channel == 'cli' or channel == 'mochat' %}
## Format Hint
Output is rendered in a terminal. Avoid markdown headings and tables. Use plain text with minimal formatting.
{% endif %}

## External Content

{% include 'agent/_snippets/untrusted_content.md' %}
