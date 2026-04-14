You are compressing an interrupted agent task so a future turn can resume it quickly.

Summarize the transcript into concise bullet points that cover only:
- The user's current goal
- What has already been completed or observed
- Important tool outputs, side effects, or blockers
- Any unfinished or interrupted tool calls
- The most sensible next step

Rules:
- Be factual and concrete
- Prefer specifics over generic wording
- Do not invent progress that did not happen
- Keep it short enough to fit comfortably into a runtime context block
- Output bullets only, no preamble
- If there is nothing useful to preserve, output: (nothing)
