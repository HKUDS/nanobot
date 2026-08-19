Create a memory overview for only the final {{ archive_count }} conversation messages immediately before this instruction. Earlier messages are context for resolving references; do not summarize them again.

Do not call tools. Return only the overview, following these memory rules:

{% include 'agent/consolidator_archive.md' %}
