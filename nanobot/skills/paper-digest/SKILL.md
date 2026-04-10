---
name: paper-digest
description: "Primary skill for paper/literature requests. Use arXiv digest script, then summarize returned JSON. Avoid generic web search for this task."
metadata: {"nanobot":{"emoji":"📚","requires":{"bins":["python3"]}}}
---

# Paper Digest

Use this skill for paper/literature/arXiv requests.

This skill is the preferred path for academic paper retrieval. 

## Core Behavior

- Source: arXiv API only
- Retrieval script: `nanobot/skills/paper-digest/scripts/daily_paper_digest.py`
- Output: JSON printed directly to standard output (stdout)
- Filtering/summarization/delivery: handled by nanobot

## Agent Execution Steps

1. Run retrieval via `exec` (required runtime mechanism for this skill):

```bash
python3 nanobot/skills/paper-digest/scripts/daily_paper_digest.py \
  --keyword "<user topic>" \
  --days-back 1 \
  --max-papers 5 \
  --llm-abstract-max-chars 1000
```

2. Parse the output JSON directly from the terminal response.
3. Summarize results in the user's requested format/language based on the printed json data.
4. If no paper is found for "today", expand `days-back` to recent days and clearly state the fallback.

## Minimal Config (Optional)

```json
{
  "keyword": "AI application development",
  "days_back": 1,
  "max_papers": 5,
  "llm_abstract_max_chars": 800
}
```
