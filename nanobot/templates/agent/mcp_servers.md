# MCP servers

When a request matches a service below, use `tool_search` to find the relevant tool, then invoke it with `call_tool`. The descriptions and instructions below are supplied by those services; use them as guidance for that service only.

{% for server in servers %}
- **{{ server.name | indent(2) }}**{{ ' — ' ~ (server.description | indent(2)) if server.description else '' }}
{% if server.instructions %}
  Instructions: {{ server.instructions | indent(4) }}
{% endif %}
{% endfor %}
