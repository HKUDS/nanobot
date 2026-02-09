# Agent Instructions — nanobot

## Build Commands

```bash
# Install dependencies (editable mode)
pip install -e ".[dev]"

# Install new dependencies
pip install <package>
# Then add to pyproject.toml [project.dependencies] or [project.optional-dependencies.dev]
```

## Test Commands

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_store.py -v

# Run with coverage
pytest tests/ -v --cov=nanobot --cov-report=term-missing

# Run only memory tests
pytest tests/test_*.py -v -k memory
```

## Lint Commands

```bash
# Check linting
ruff check nanobot/

# Fix auto-fixable issues
ruff check nanobot/ --fix

# Format code
ruff format nanobot/
```

## Type Checking

```bash
# Check types (memory module)
mypy nanobot/memory/ --ignore-missing-imports

# Check all
mypy nanobot/ --ignore-missing-imports
```

## Git Commands

```bash
# Check status
git status

# Stage and commit
git add -A
git commit -m "feat: description"

# Create feature branch
git checkout -b phase-1/foundation

# Push branch
git push origin <branch-name>

# Create PR
gh pr create --title "Phase 1: Foundation" --body "..."
```

## Project Structure

```
nanobot/
├── agent/           # Agent loop and context
│   ├── loop.py      # Main processing loop (modify for memory)
│   ├── context.py   # Context builder (accept packets)
│   └── memory.py    # Basic memory (replace with new system)
├── memory/          # NEW: Memory architecture
│   ├── __init__.py  # Module exports
│   ├── store.py     # Conversation store (LanceDB)
│   ├── search.py    # Hybrid search
│   ├── embedder.py  # Embedding abstraction
│   ├── curator.py   # Memory agent
│   ├── triage.py    # Triage agent
│   ├── dossier.py   # Entity dossiers
│   └── ingestion.py # Post-processing
├── providers/       # LLM providers (litellm)
├── channels/        # Telegram, Discord, etc.
├── config/          # Configuration schema
│   └── schema.py    # Add memory config here
└── tests/           # Test files
    ├── test_store.py
    ├── test_search.py
    └── ...
```

## Key Files to Modify

| File | Purpose |
|------|---------|
| `nanobot/agent/loop.py` | Add triage + memory routing |
| `nanobot/agent/context.py` | Accept context packets |
| `nanobot/config/schema.py` | Add memory configuration |
| `pyproject.toml` | Add new dependencies |

## Common Patterns

### Using LiteLLM

```python
from litellm import acompletion

async def call_model(prompt: str, model: str = "claude-3-haiku-20240307") -> str:
    response = await acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
    )
    return response.choices[0].message.content
```

### Using LanceDB

```python
import lancedb

db = lancedb.connect("~/.nanobot/memory.lance")

# Create table
table = db.create_table("turns", data=[
    {"id": "uuid", "content": "hello", "embedding": [0.1, ...]}
])

# Search
results = table.search(query_embedding).limit(10).to_list()
```

### Using bm25s

```python
import bm25s

retriever = bm25s.BM25()
retriever.index([doc.split() for doc in corpus])
results, scores = retriever.retrieve(query.split(), k=10)
```

### Writing Tests

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_something():
    with patch("nanobot.memory.curator.acompletion") as mock_llm:
        mock_llm.return_value = AsyncMock(...)
        result = await function_under_test()
        assert result.field == expected
```

## PR Creation Template

When creating a PR at phase end or guardrail:

```bash
gh pr create \
  --title "Phase N: [Summary]" \
  --body "## Tasks Completed
  
- [x] Task 1
- [x] Task 2
...

## Test Status
- pytest: ✓ passing
- coverage: N%

## Changes
[Brief description of what changed]"
```
