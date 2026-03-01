# File Search / RAG

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/file-search

## What It Is

Built-in Retrieval Augmented Generation (RAG). Imports, chunks, indexes documents for fast semantic search. No external vector database needed.

## Gemini API Capabilities

### How it works

1. **Create a File Search store** — persistent container for embeddings
2. **Upload and import files** — auto-chunked, embedded, indexed
3. **Query with FileSearch tool** — semantic search against stores

### Features

- Semantic search (not keyword matching)
- Configurable chunking (tokens per chunk, overlap)
- Custom metadata + filtering (`author="Robert Graves"`)
- Citations in responses with source chunk references
- Structured output (Gemini 3) — JSON schema + File Search combined
- Embeddings persist indefinitely until deleted

### Supported file types

PDF, Word, Excel, PowerPoint, JSON, SQL, Jupyter notebooks, LaTeX, Kotlin, Dart, Markdown, HTML, CSS, XML, CSV, YAML, and many more. Max 100MB per file.

### Storage limits

| Tier | Storage |
|------|---------|
| Free | 1 GB |
| Tier 1 | 10 GB |
| Tier 2 | 100 GB |
| Tier 3 | 1 TB |

### Pricing

- Indexing: $0.15 per 1M tokens
- Storage: free
- Query embeddings: free
- Retrieved tokens: standard context token rates

### Supported models

Gemini 3.1 Pro, 3 Flash, 2.5 Pro, 2.5 Flash-Lite

### Limitations

- Cannot combine with Google Search, URL Context, or other tools
- Not supported in Live API

## Nanobot Implementation

Not implemented. Memory is session-based (`scorpion/session/manager.py`) using text history, not vector embeddings.

**What File Search would enable:**
- Upload knowledge base documents for the bot to reference
- Semantic search over workspace files
- Cited answers from uploaded documents
- No external vector DB dependency
