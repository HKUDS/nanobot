# Long Task — FINAL Step {{ step + 1 }}/{{ max_steps }}

**This is one of the LAST steps. You are running out of budget.**

## Goal
{{ goal }}

{% if cumulative_history %}
## Run history (prior steps)
Summaries from **earlier** completed steps. Use with **Previous Progress** below.

{{ cumulative_history }}
{% endif %}
{% if all_files_created_so_far or all_files_modified_so_far %}
### All files touched so far (entire run)
{% for f in all_files_created_so_far %}
- Created: `{{ f }}`
{% endfor %}
{% for f in all_files_modified_so_far %}
- Modified: `{{ f }}`
{% endfor %}
{% endif %}

## Previous Progress
{% if handoff.message %}
{{ handoff.message }}
{% endif %}
{% if handoff.files_created or handoff.files_modified %}

### Files Changed
{% for f in handoff.files_created %}
- Created: `{{ f }}`
{% endfor %}
{% for f in handoff.files_modified %}
- Modified: `{{ f }}`
{% endfor %}
{% endif %}

## Instructions
1. **Do NOT start new work**. Only finish what is already in progress.
2. **Wrap up**: Complete any partial work, write final results to files.
3. **Final handoff**: Call `handoff()` with a clear summary of what remains unfinished. Call `complete()` ONLY if you are 100% sure everything is done.

You have {{ budget }} tool calls total. Reserve the last 1-2 calls for `handoff()` or `complete()`.
