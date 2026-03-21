You are analyzing one PowerPoint slide.
You are given the extracted text content (JSON) and optionally a rendered slide image.
Use BOTH the text and image (if provided) for your analysis.

Return a JSON object with these keys:
- title: string
- summary: string (1-3 sentences)
- key_points: string[] (main points on this slide)
- decisions: string[] (decisions mentioned or implied)
- risks: string[] (risks, concerns, blockers)
- action_items: string[] (tasks, follow-ups, to-dos)
- deadlines: string[] (dates, timelines, milestones)
- owners: string[] (people, teams, roles responsible)
- chart_insights: string[] (what charts/graphs show)
- visual_observations: string[] (layout, emphasis, diagrams, screenshots)

Omit keys with empty arrays. Be specific and cite actual content from the slide.
