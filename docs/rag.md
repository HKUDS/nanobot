# Retrieval-Augmented Generation (RAG)

Nanobot supports optional RAG-based memory retrieval for more relevant context injection.

## Overview

When RAG is enabled, the agent uses semantic search to retrieve only the most relevant memory chunks instead of loading the full MEMORY.md file. This:

- Reduces token usage for large memory files
- Improves context relevance for specific queries
- Maintains privacy with local embeddings (no cloud API calls)

## Configuration

Add to your `config.json`:

```json
{
  "agents": {
    "defaults": {
      "rag": {
        "enabled": true,
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "chunk_size": 512,
        "chunk_overlap": 50,
        "top_k": 5,
        "min_relevance_score": 0.3,
        "max_context_chars": 8000,
        "index_on_startup": true,
        "reindex_interval_hours": 24
      }
    }
  }
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `false` | Enable RAG-based memory retrieval |
| `embedding_model` | string | `"sentence-transformers/all-MiniLM-L6-v2"` | Local embedding model (sentence-transformers) |
| `chunk_size` | int | `512` | Characters per chunk |
| `chunk_overlap` | int | `50` | Overlap between chunks |
| `top_k` | int | `5` | Number of chunks to retrieve |
| `min_relevance_score` | float | `0.3` | Minimum similarity score (0-1) |
| `max_context_chars` | int | `8000` | Maximum characters for retrieved context |
| `index_on_startup` | bool | `true` | Index memory on agent startup |
| `reindex_interval_hours` | int | `24` | Hours between automatic reindexing |

## Installation

RAG requires the `sentence-transformers` package:

```bash
pip install sentence-transformers
```

## How It Works

1. **Document Loading**: MEMORY.md and history.jsonl are loaded as documents
2. **Text Splitting**: Documents are split into overlapping chunks (LangChain-style recursive splitter)
3. **Embedding**: Each chunk is embedded using sentence-transformers (local, privacy-first)
4. **Vector Store**: In-memory vector store with cosine similarity search
5. **Retrieval**: Top-k chunks are retrieved based on query similarity

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RAG Pipeline                              │
├─────────────────────────────────────────────────────────────┤
│  Document → TextSplitter → Embeddings → VectorStore         │
│                                                              │
│  Query → Embed → Similarity Search → Retrieved Context      │
└─────────────────────────────────────────────────────────────┘
```

### Components (LangChain-style)

- **Document**: Text content with metadata
- **TextSplitter**: Recursive character-based splitting
- **Embeddings**: Local sentence-transformers
- **VectorStore**: In-memory similarity search
- **Retriever**: Top-k retrieval interface

## When to Use RAG

RAG is beneficial when:

- Your MEMORY.md file is large (>10KB)
- You have many history entries (>100)
- You want query-specific context
- Token usage is a concern

For small memory files, the default full-memory injection may be sufficient.

## Example

With RAG enabled, a query like "What's the status of my training job?" will:

1. Embed the query
2. Search for similar chunks in memory/history
3. Retrieve top-5 relevant chunks
4. Inject only those chunks into the context

Instead of loading the entire MEMORY.md file.

## Performance

- **Embedding model**: all-MiniLM-L6-v2 (384 dimensions, ~25ms per query)
- **Memory usage**: In-memory vector store, scales with chunk count
- **Startup time**: Indexing takes ~1-2 seconds for typical memory files

## Limitations

- In-memory only (no persistence between restarts)
- Requires sentence-transformers installation
- Not suitable for very large document collections (>100K chunks)