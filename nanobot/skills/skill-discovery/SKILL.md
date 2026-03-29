---
name: skill-discovery
description: Find skills by keyword search.
metadata: {"nanobot": {"emoji": "🔍"}}
---

# Skill Discovery

Find skills when you don't know which one to use.

## Search

```bash
python {baseDir}/scripts/search_skills.py -q "keyword" [-l N] [--json]
```

**Options:** `-l` limit results, `--json` machine output, `--no-rg` disable ripgrep.

## Workflow

1. Extract keywords from user request
2. Search: `python {baseDir}/scripts/search_skills.py -q "keywords"`
3. Read: `cat <path-from-results>`
4. If no local match → use **clawhub** skill

## Tips

- Multiple keywords narrow results
- Use both user language and English for better coverage
