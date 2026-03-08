---
name: arxiv-vla-papers
description: Query and summarize latest Vision-Language-Action (VLA) papers from arXiv. Use when user asks for recent VLA papers, robotic manipulation papers, vision-language-action research, or wants to track latest developments in embodied AI. Supports filtering by date range (today, 2 days, 1 week) and categories (AI, CV, HCI, ML, Robotics). Automatically summarizes papers focusing on innovations, methods, and differences from prior work.
metadata: {"nanobot":{"emoji":"📄","requires":{"bins":["python3","jq"]}}}
---

# arXiv VLA Papers

Query and summarize the latest Vision-Language-Action (VLA) papers from arXiv, focusing on robotic manipulation and navigation.

## Overview

This skill queries arXiv for recent Vision-Language-Action papers, filters by relevant categories and keywords, and provides concise summaries highlighting innovations, methods, and differences from prior work.

## Quick Start

### Query recent papers

The script is located at `scripts/arxiv_query.py` relative to this skill directory. Use the full path to the script:

```bash
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 7 --max-results 10
```

Or if the skill is in workspace skills, use:
```bash
python3 skills/arxiv-vla-papers/scripts/arxiv_query.py --days 7 --max-results 10
```

**Note**: The agent can determine the correct path by reading this SKILL.md file location and constructing the path to `scripts/arxiv_query.py`.

### Get JSON output for processing

```bash
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 2 --json > papers.json
```

## Workflow

### 1. Query arXiv for papers

Use the script to fetch papers matching VLA criteria:

```bash
# Last 7 days (default)
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 7

# Last 2 days
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 2

# Today only (1 day)
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 1

# More results
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 7 --max-results 30
```

The script searches for papers containing:
- Keywords: vision-language-action, robotic manipulation, language-conditioned, instruction following, embodied AI
- Categories: cs.AI, cs.CV, cs.HC, cs.LG, cs.RO

### 2. Fetch paper details

For each paper, use `web_fetch` to get the abstract page:

```json
{
  "url": "https://arxiv.org/abs/2401.12345",
  "extractMode": "markdown",
  "maxChars": 5000
}
```

Or fetch the PDF if full text is needed:

```json
{
  "url": "https://arxiv.org/pdf/2401.12345.pdf",
  "extractMode": "text",
  "maxChars": 20000
}
```

### 3. Summarize papers

Use the `summarize` skill to extract key insights:

```bash
summarize "https://arxiv.org/abs/2401.12345" --model google/gemini-3-flash-preview --length medium
```

Or use LLM directly with a focused prompt:

```
Summarize this VLA paper focusing on:
1. Main innovation/contribution
2. Key methods and approach
3. How it differs from prior work
4. Experimental results (if mentioned in abstract)
```

## Customization

### Adjust date range

```bash
# Last week
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 7

# Last 2 days
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 2

# Today only
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 1

# No date filter (all papers)
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --no-date-filter
```

### Custom categories

```bash
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --categories cs.RO cs.CV
```

### Additional keywords

```bash
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --keywords "mobile manipulation" "dexterous manipulation"
```

## Output Format

The script returns papers with:
- Title
- Authors
- Publication date
- Abstract
- arXiv URL (abs and PDF)
- Categories

## Integration with Other Skills

### Use with summarize

After fetching paper URLs, use `summarize` for detailed analysis:

```bash
# Get paper list
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 7 --json > papers.json

# Summarize each paper
for url in $(jq -r '.[].abs_url' papers.json); do
  summarize "$url" --model google/gemini-3-flash-preview --length medium
done
```

### Use with web_fetch

Fetch full abstracts or PDFs for deeper analysis:

```bash
# Get paper URLs
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 2 --json | jq -r '.[].abs_url' | head -5
```

## Focus Areas

When summarizing papers, emphasize:

1. **Innovation**: What's new? What problem does it solve?
2. **Method**: How does it work? Architecture, training, inference?
3. **Differences**: How does it differ from prior work? What's the key improvement?
4. **Results**: Performance metrics, benchmarks, real-world validation (if available in abstract)

## Example Workflow

### Complete workflow: Query → Fetch → Summarize

```bash
# 1. Query recent papers (last 7 days)
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 7 --max-results 10 --json > papers.json

# 2. Extract top 5 papers
jq '.[:5]' papers.json > top5.json

# 3. For each paper, fetch and summarize
for url in $(jq -r '.[].abs_url' top5.json); do
  echo "=== $url ==="
  summarize "$url" --model google/gemini-3-flash-preview --length medium
  echo ""
done
```

### Quick summary of today's papers

```bash
# Get today's papers and summarize each
python3 nanobot/skills/arxiv-vla-papers/scripts/arxiv_query.py --days 1 --json | \
  jq -r '.[].abs_url' | \
  while read url; do
    echo "Summarizing: $url"
    summarize "$url" --model google/gemini-3-flash-preview --length short
    echo "---"
  done
```

### Focused analysis with custom prompt

For each paper URL, use `web_fetch` to get the abstract, then ask LLM to summarize with focus on innovations:

1. Fetch abstract: `web_fetch` with `url: "https://arxiv.org/abs/XXXXX"`
2. Summarize with prompt: "Focus on: (1) main innovation, (2) key methods, (3) differences from prior work"

## References

- `references/arxiv_api.md` - arXiv API documentation and query syntax

## Notes

- arXiv API has no authentication but rate limit ~1 request per 3 seconds
- Abstract pages are usually sufficient for summarization
- PDFs can be fetched for full text analysis but are larger
- Categories are automatically filtered to VLA-relevant areas
- Keywords focus on robotic manipulation and navigation contexts
