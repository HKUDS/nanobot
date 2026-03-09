---
name: python-scripts
description: Write and execute Python scripts using uv for programmatic tasks.
---

Use Python when a step needs data transformation, API calls, calculations, or deterministic operations where code is more reliable than natural language.

## How to Use

Write a script with inline dependencies and run it with `uv run`:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
# ]
# ///

import json
import requests

data = requests.get("https://api.example.com/data").json()
print(json.dumps(data))
```

```bash
uv run script.py
```

The `# /// script` block declares dependencies - `uv` installs them automatically.

## Output Conventions

- **Structured data**: Print JSON to stdout
- **Progress/debug info**: Print to stderr
- **Errors**: Print to stderr and exit with non-zero code

```python
import sys
import json

# Output result
print(json.dumps({"items": [...], "count": 42}))

# Debug info (won't pollute output)
print("Processed 42 items", file=sys.stderr)
```

## When to Use Python vs LLM

**Use Python for:** JSON manipulation, API calls with auth/pagination, calculations, file parsing, sorting/filtering, large datasets

**Keep as LLM for:** Tasks requiring judgment, natural language generation, flexible interpretation
