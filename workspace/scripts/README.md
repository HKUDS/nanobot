# Workspace scripts

Custom local integrations used by nanobot via `exec` tool.

## Scripts

- `searxng_search.py` — search via local SearXNG (`http://localhost:8080`)
- `qdrant_store.py` — embed text with Mistral and store in Qdrant
- `qdrant_find.py` — semantic search in Qdrant using Mistral embeddings

## Required env for Qdrant scripts

- `MISTRAL_API_KEY`

Optional:
- `MISTRAL_API_BASE` (default `https://api.mistral.ai/v1`)
- `QDRANT_URL` (default `http://localhost:6333`)

## Quick check

```bash
python3 workspace/scripts/searxng_search.py "nanobot"
python3 workspace/scripts/qdrant_store.py "test memory"
python3 workspace/scripts/qdrant_find.py "test"
```
