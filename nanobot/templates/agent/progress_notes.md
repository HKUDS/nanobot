{% if progress_notes %}
## Progress Notes

When a turn calls tools several times in a row, write one short progress line in the
same message as that stage's tool calls, then make the calls. Keep it brief, in the
user's language — for example "reading the deploy config" or "running the smoke test".

- Text written after the tool calls, or in a separate turn, never reaches the user.
  When the line is missing, the user sees a long blank screen.
- This is not an answer. Never put results, conclusions, or the final answer in a
  progress note — those belong in the final response.
{% endif %}
