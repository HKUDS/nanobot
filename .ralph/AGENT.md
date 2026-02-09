# Agent Instructions — nanobot

## Build Commands

```bash
# Install dependencies (editable mode for development)
pip install -e ".[dev]"

# Install new dependencies (then add to pyproject.toml)
pip install <package>

# Build package
python -m build
```

## Test Commands

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_store.py -v

# Run with coverage
pytest tests/ -v --cov=nanobot --cov-report=term-missing

# Run async tests (already configured via pytest-asyncio)
pytest tests/ -v
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
# Optional: run mypy if installed
mypy nanobot/ --ignore-missing-imports
```

## Project Structure

```
nanobot/
├── agent/           # Agent loop and context
├── channels/        # Telegram, Discord, WhatsApp, etc.
├── cli/             # CLI commands (typer)
├── config/          # Configuration schema and loading
├── cron/            # Scheduled tasks
├── memory/          # NEW: Memory architecture (our focus)
├── providers/       # LLM providers (litellm-based)
├── session/         # Session management
└── utils/           # Helpers
```

## Key Files for Memory Implementation

- `nanobot/memory/store.py` — Conversation turn storage (LanceDB)
- `nanobot/memory/search.py` — Hybrid vector + BM25 search
- `nanobot/memory/embedder.py` — Embedding abstraction
- `nanobot/memory/curator.py` — Memory agent (context synthesis)
- `nanobot/memory/triage.py` — Triage agent (fast path routing)
- `nanobot/memory/dossier.py` — Entity dossiers
- `nanobot/memory/ingestion.py` — Post-conversation processing

## Integration Points

- `nanobot/agent/loop.py` — Main agent loop, add triage and memory routing
- `nanobot/agent/context.py` — Context builder, accept context packets
- `nanobot/config/schema.py` — Add memory configuration options

## Git Workflow

```bash
# Check status
git status

# Stage and commit
git add -A
git commit -m "feat: description of change"

# Push (if needed)
git push origin main
```

## Common Patterns

### Adding a new module

1. Create `nanobot/memory/newmodule.py`
2. Add exports to `nanobot/memory/__init__.py`
3. Create `tests/test_newmodule.py`
4. Run tests: `pytest tests/test_newmodule.py -v`
5. Run lint: `ruff check nanobot/memory/newmodule.py`

### Using LiteLLM for small model calls

```python
from litellm import acompletion

response = await acompletion(
    model="claude-3-haiku-20240307",  # or configured model
    messages=[{"role": "user", "content": prompt}],
    max_tokens=500,
)
result = response.choices[0].message.content
```

### Using LanceDB

```python
import lancedb

db = lancedb.connect("~/.nanobot/memory.lance")
table = db.create_table("turns", data=[...], mode="overwrite")
results = table.search(embedding).limit(10).to_list()
```

### Using bm25s

```python
import bm25s

retriever = bm25s.BM25()
retriever.index([doc.split() for doc in corpus])
results, scores = retriever.retrieve(query.split(), k=10)
```
