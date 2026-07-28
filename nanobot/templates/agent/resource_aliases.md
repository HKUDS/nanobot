## Resource Aliases

These stable filesystem aliases are available:
{% for label, path in aliases %}
- {{ label }}: `{{ path }}`
{% endfor %}

Aliases are alternative path names only; they do not grant additional file or shell permissions. A sandboxed shell may not expose an alias even when a file tool can use it. Continue to use paths relative to the current project workspace for project files.
