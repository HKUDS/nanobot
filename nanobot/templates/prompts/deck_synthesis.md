You are synthesizing a complete PowerPoint deck analysis.
You are given per-slide analyses as a JSON array.

Return a JSON object with these keys:
- executive_summary: string (concise 2-4 paragraph overview of the entire deck)
- risks: string[] (all risks across the deck, with slide numbers, deduplicated)
- decisions: string[] (all decisions, with slide numbers)
- action_items: string[] (all action items, include owners and deadlines where known)
- deadlines: string[] (all deadlines and timelines mentioned)
- unanswered_questions: string[] (gaps, unclear points, missing information)
- themes: string[] (recurring themes across the deck)

Be thorough. Always cite slide numbers. Deduplicate across slides.
