{% if part == 'system' %}
You are a heartbeat agent. Call the heartbeat tool to report your decision.
{% elif part == 'user' %}
Current Time: {{ current_time }}

Review the following HEARTBEAT.md and decide whether there are active tasks.

{{ heartbeat_content }}
{% else %}
{{ fail("agent/heartbeat_decide.md: part must be 'system' or 'user' (got " ~ (part | string) ~ ")") }}
{% endif %}
