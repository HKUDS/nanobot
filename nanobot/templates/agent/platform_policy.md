{% if system == 'Windows' %}
- Do not assume GNU tools like `grep`, `sed`, or `awk` exist.
- Prefer Windows-native commands or file tools when they are more reliable.
- If terminal output is garbled, retry with UTF-8 output enabled.
{% else %}
- Prefer UTF-8 and standard shell tools.
- Use file tools when they are simpler or more reliable than shell commands.
{% endif %}
