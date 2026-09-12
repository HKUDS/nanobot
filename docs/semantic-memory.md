# Semantic memory

Nanobot can optionally supplement Dream and its file-backed memory with a derived
PostgreSQL/pgvector index. It does **not** replace `SOUL.md`, `USER.md`,
`memory/MEMORY.md`, or `memory/history.jsonl`.

## Data flow

1. Existing session consolidation appends curated summaries to `history.jsonl`.
2. The semantic service indexes new or changed history records plus bounded chunks
   of `USER.md` and `MEMORY.md`.
3. Before a user turn, hybrid pgvector and PostgreSQL full-text search retrieves
   a broad candidate set. A local deterministic reranker computes a candidate
   selection using relevance, source durability, importance and confidence.
   The default `rerankMode: "shadow"` keeps the baseline search order in the
   prompt and records comparison metrics only. `"active"` requires an explicit
   opt-in after representative recall evaluation. Optimizer errors fall back
   to baseline rather than suppressing recall.
   Deduplication removes only whitespace-equivalent copies from transient
   context, preserving negation, identifiers, dates and additional facts.
   It never deletes source records or derived index entries.
4. Recall is injected as transient, explicitly untrusted runtime context. It is
   removed before session persistence so recalled text cannot recursively feed
   future archives. Because opaque provider continuation payloads cannot be
   selectively scrubbed, Nanobot also drops local provider continuation state for
   any turn (including an injected follow-up) that received transient recall.

PostgreSQL and the local embedding model are fail-open dependencies: if either is
unavailable, the agent answers using its existing memory behavior.

## Installation

```bash
pip install 'nanobot-ai[semantic-memory]'
```

Provision PostgreSQL with the `vector` extension. The application role needs a
dedicated database in which it may create the `nanobot_memory` schema and tables,
but does not need superuser or extension-creation privileges.

## Configuration

```json
{
  "agents": {
    "defaults": {
      "semanticMemory": {
        "enabled": true,
        "dsnFile": "/path/to/postgresql.env",
        "namespace": "personal-agent",
        "scope": "workspace",
        "embeddingModel": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "embeddingDimension": 384,
        "topK": 8,
        "candidateK": 40,
        "rerankEnabled": true,
        "rerankMode": "shadow",
        "minVectorSimilarity": 0.15,
        "maxContextChars": 6000,
        "pollIntervalS": 60
      }
    }
  }
}
```

Use `scope: "session"` for multi-user or untrusted shared workspaces. Workspace
scope intentionally allows cross-session personal recall.

The DSN file may contain either `DATABASE_URL` or standard `PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD`, and `PGSSLMODE` fields. Protect it with mode
`0600`. A direct `dsn` field and `${ENV_VAR}` interpolation are also supported,
but a separate file avoids serializing credentials into the main config.

## Administration

```bash
nanobot-memory status
nanobot-memory reconcile
nanobot-memory reindex
nanobot-memory search 'What did we decide about PostgreSQL?'
nanobot-memory forget history cursor:42:chunk:0 --yes
nanobot-memory purge --yes
```

`purge` removes only the derived index. It does not modify Dream or workspace
memory files. `reconcile` reconstructs missing records from available source
files, while `reindex` regenerates embeddings for all currently available source
chunks.

## Security and retention

- Retrieved text is data, never executable instruction.
- Common credentials are redacted before indexing.
- Query text is logged only as SHA-256, not plaintext.
- Every record retains source type and reference.
- `history.jsonl` compaction does not implicitly delete older indexed episodes.
  Use `purge` and then `reconcile` for an explicit rebuild.
- Back up PostgreSQL independently and test restoration regularly.

## Shadow evaluation and rollback

The additive `retrieval_log` migration records mode, candidate/hit counts,
selection overlap and excerpt character counts without memory content. These are
proxy metrics: overlap is not recall accuracy and shorter text is not necessarily
better. Compare against labeled tasks covering preferences, decisions, corrections,
negations and active goals before enabling active selection. Unit fixtures are
regression checks, not proof of better real-world recall.

No canary or automatic configuration promotion is enabled. Keep `rerankMode` at
`shadow` until the evaluation gate passes. To undo active ranking, set the mode
back to `shadow` and reload the gateway in a controlled maintenance window; the
underlying memory and hybrid index remain intact. Optimizer exceptions already
fall back to baseline within a request, without altering configuration.
