# Long Task — Step {{ step + 1 }}/{{ max_steps }}

You are one step in a chain working toward a goal.

## Goal
{{ goal }}

{% if cumulative_history %}
## Run history (prior steps)
Summaries from **earlier** completed steps (not only the last handoff). Use this so constraints and plans from step 1 are not lost.

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
{% if handoff.next_step_hint %}

### Suggested Next Step
{{ handoff.next_step_hint }}
{% endif %}
{% if handoff.verification %}

### Verification
{{ handoff.verification }}
{% endif %}

## Instructions
1. **Check existing work**: Use the file list above — do NOT re-explore files already handled.
2. **Do the next chunk**: Make concrete progress. Write results to files.
3. **Handoff**: Call `handoff()` with your progress summary, files changed, and a hint for the next step. Call `complete()` only if the ENTIRE goal is achieved.

You have {{ budget }} tool calls total. Reserve the last 1-2 calls for `handoff()` or `complete()`.
