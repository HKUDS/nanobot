# Batch API

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/batch-api

## What It Is

Process large volumes of requests asynchronously at 50% cost. Targets 24-hour turnaround (often faster). For data preprocessing, evaluations, and bulk operations.

## Gemini API Capabilities

### Input methods

| Method | Max size | Best for |
|--------|----------|----------|
| Inline | 20MB | Smaller batches |
| JSONL files | 2GB | Large volumes |

### Supported operations

- Text generation (any config)
- Image generation (Nano Banana)
- Embeddings (`batches.create_embeddings`)
- Structured outputs with schemas
- System instructions and tools (Google Search, etc.)
- Multimodal inputs

### Job states

`PENDING` → `RUNNING` → `SUCCEEDED` / `FAILED` / `CANCELLED` / `EXPIRED` (48h limit)

### Management

- `batches.create()` — submit job
- `batches.list()` — list recent jobs
- `batches.cancel()` — cancel ongoing
- `batches.delete()` — delete job

### Pricing

50% of standard rates. Context caching hits billed at standard traffic rates.

## Nanobot Implementation

Not implemented. All requests are processed sequentially one-by-one in the agent loop.

**Potential use:** bulk message processing, scheduled batch operations, embedding generation for knowledge base indexing.
