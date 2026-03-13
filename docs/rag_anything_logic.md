# Rag-Anything Logic Implementation

This document provides a deep dive into the implementation logic of the **Rag-Anything** integration within Nanobot.

## 1. Architecture Overview

The integration bridges Nanobot's tool system with the `raganything` library. It is designed to be:
- **Lazy Loaded:** The heavy RAG engine initializes only when first used.
- **Dual-Model:** The Agent and the RAG system can use different LLMs.
- **Configurable:** Settings are drawn from both `config.json` and a dedicated `.env` file.

## 2. Initialization Logic (`_load_rag_env`)

Before the `RagTool` class is even instantiated, `nanobot/agent/tools/rag.py` executes `_load_rag_env`.

### 2.1. Environment Injection
The code dynamically locates the `.env` file from the parent `RAG-Anything` project and injects its variables into `os.environ`.

**Path Resolution:**
```python
# Resolves relative to nanobot/agent/tools/rag.py
rag_env_path = os.path.abspath(os.path.join(current_dir, "../../../../../RAG/RAG-Anything/.env"))
```

**Why this matters:** `raganything` relies on environment variables (like `SEEKDB_API_KEY`) being present in `os.environ`. Nanobot ensures these are loaded without requiring the user to manually source them.

## 3. The `RagTool` Class

### 3.1. Lazy Initialization
To keep the gateway startup fast, we **do not** create the `CustomRAGAnything` instance in `__init__`. Instead, it happens inside `execute()`:

```python
if not self._rag_instance:
    logger.info("Initializing RAG instance...")
    self._rag_instance = CustomRAGAnything(...)
```

### 3.2. Dual Model Configuration
A key feature is the separation of concerns between the **Agent's Brain** and the **RAG's Brain**.

- **Agent LLM:** Configured in `providers` (e.g., `qwen2.5-72b`). Handles conversation and tool routing.
- **RAG LLM & Embedder:** Configured in `tools.rag` (e.g., `Ministral-3b`, `snowflake-arctic-embed`). Handles context summarization and vector retrieval.

**Configuration parameters passed to `CustomRAGAnything`:**
- `llm_binding`: `openai` (usually)
- `llm_model_name`: From `config.json`
- `llm_base_url`: From `config.json`
- `embed_model_name`: From `config.json`
- `working_dir`: Fixed to `<nanobot_root>/rag_storage`

## 4. Execution Flow (`execute`)

When the Agent calls `rag_query(query="...", mode="hybrid")`:

1.  **Availability Check:** Returns an error if `raganything` library is missing or if RAG is disabled in config.
2.  **Instance Creation:** (If first run) Initializes the RAG engine.
3.  **Mode Mapping:** Maps user-friendly "hybrid" mode to the library's internal "mix" mode.
4.  **Query Execution:** Calls `await self._rag_instance.aquery(query)`.
5.  **Logging:** Logs the raw result length and content (truncated) for debugging.

## 5. Dependency Management

The integration requires the `raganything` package to be in the python path. Nanobot handles import errors gracefully:

```python
try:
    from raganything.sunteco.sunteco_rag_anything import CustomRAGAnything
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
```

If imports fail, the gateway starts but the RAG tool returns a helpful error message instead of crashing.
