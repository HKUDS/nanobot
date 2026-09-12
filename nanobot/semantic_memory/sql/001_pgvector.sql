-- Semantic memory is a derived supplement to Dream and workspace memory files.
CREATE SCHEMA IF NOT EXISTS nanobot_memory;

CREATE TABLE IF NOT EXISTS nanobot_memory.collections (
    workspace_namespace text PRIMARY KEY,
    embedding_model text NOT NULL,
    embedding_dimension integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS nanobot_memory.items (
    id bigserial PRIMARY KEY,
    workspace_namespace text NOT NULL,
    embedding_model text NOT NULL,
    source_type text NOT NULL,
    source_key text NOT NULL,
    source_timestamp text,
    session_key text,
    kind text NOT NULL DEFAULT 'episodic',
    content text NOT NULL,
    content_hash text NOT NULL,
    importance real NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
    confidence real NOT NULL DEFAULT 0.8 CHECK (confidence BETWEEN 0 AND 1),
    status text NOT NULL DEFAULT 'active',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(384) NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_accessed_at timestamptz,
    UNIQUE (workspace_namespace, embedding_model, source_type, source_key)
);

CREATE INDEX IF NOT EXISTS semantic_memory_items_hnsw
    ON nanobot_memory.items USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS semantic_memory_items_fts
    ON nanobot_memory.items USING gin (search_vector);
CREATE INDEX IF NOT EXISTS semantic_memory_items_scope
    ON nanobot_memory.items (workspace_namespace, embedding_model, status, session_key);

CREATE TABLE IF NOT EXISTS nanobot_memory.tombstones (
    workspace_namespace text NOT NULL,
    source_type text NOT NULL,
    source_key text NOT NULL,
    content_hash text,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_namespace, source_type, source_key)
);

CREATE TABLE IF NOT EXISTS nanobot_memory.retrieval_log (
    id bigserial PRIMARY KEY,
    workspace_namespace text NOT NULL,
    session_key text,
    query_hash text NOT NULL,
    hit_count integer NOT NULL,
    latency_ms integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE nanobot_memory.tombstones
    ADD COLUMN IF NOT EXISTS content_hash text;

CREATE TABLE IF NOT EXISTS nanobot_memory.forgotten_content (
    workspace_namespace text NOT NULL,
    content_hash text NOT NULL,
    source_type text NOT NULL,
    source_key text NOT NULL,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_namespace, content_hash)
);

INSERT INTO nanobot_memory.forgotten_content (
    workspace_namespace, content_hash, source_type, source_key, reason, created_at
)
SELECT workspace_namespace, content_hash, source_type, source_key, reason, created_at
FROM nanobot_memory.tombstones
WHERE content_hash IS NOT NULL
ON CONFLICT (workspace_namespace, content_hash) DO NOTHING;
