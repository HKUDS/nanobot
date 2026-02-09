# sentence-transformers Reference

sentence-transformers generates embeddings for semantic similarity.

## Installation

```bash
pip install sentence-transformers
```

## Basic Usage

```python
from sentence_transformers import SentenceTransformer

# Load a model (downloads on first use)
model = SentenceTransformer("all-MiniLM-L6-v2")

# Encode sentences
sentences = [
    "The weather is lovely today.",
    "It's so sunny outside!",
    "He drove to the stadium.",
]

# Get embeddings (numpy array)
embeddings = model.encode(sentences)
print(embeddings.shape)  # (3, 384) for all-MiniLM-L6-v2
```

## Model Choice

For conversation retrieval, recommended models:

| Model | Dimensions | Speed | Quality |
|-------|-----------|-------|---------|
| all-MiniLM-L6-v2 | 384 | Fast | Good |
| all-mpnet-base-v2 | 768 | Medium | Better |
| all-MiniLM-L12-v2 | 384 | Fast | Good |

For this project, use **all-MiniLM-L6-v2**:
- Fast inference
- 384 dimensions (smaller storage)
- Good quality for conversation retrieval

## Encoding Options

```python
# Basic encoding
embeddings = model.encode(sentences)

# With progress bar
embeddings = model.encode(sentences, show_progress_bar=True)

# Batch size (for large datasets)
embeddings = model.encode(sentences, batch_size=32)

# Normalize embeddings (for cosine similarity)
embeddings = model.encode(sentences, normalize_embeddings=True)

# Convert to specific dtype
embeddings = model.encode(sentences, convert_to_numpy=True)
embeddings = model.encode(sentences, convert_to_tensor=True)  # PyTorch tensor
```

## Computing Similarity

```python
from sentence_transformers import util

# Encode two sets of sentences
embeddings1 = model.encode(sentences1)
embeddings2 = model.encode(sentences2)

# Cosine similarity matrix
cosine_scores = util.cos_sim(embeddings1, embeddings2)

# For each sentence in set 1, get similarity to all in set 2
for i in range(len(sentences1)):
    for j in range(len(sentences2)):
        print(f"{sentences1[i]} <-> {sentences2[j]}: {cosine_scores[i][j]:.4f}")
```

## Semantic Search

```python
from sentence_transformers import util

# Corpus and query
corpus = ["doc 1", "doc 2", "doc 3"]
query = "search query"

# Encode
corpus_embeddings = model.encode(corpus, convert_to_tensor=True)
query_embedding = model.encode(query, convert_to_tensor=True)

# Find top-k most similar
hits = util.semantic_search(query_embedding, corpus_embeddings, top_k=5)

# hits[0] contains results for first query
for hit in hits[0]:
    print(f"Score: {hit['score']:.4f}, Doc: {corpus[hit['corpus_id']]}")
```

## Async Encoding Pattern

sentence-transformers is sync, but can be wrapped:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

class AsyncEmbedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)
        self.executor = ThreadPoolExecutor(max_workers=1)
    
    async def encode(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            self.executor,
            lambda: self.model.encode(texts).tolist()
        )
        return embeddings
```

## Caching Embeddings

Don't re-embed the same text:

```python
from functools import lru_cache

@lru_cache(maxsize=10000)
def get_embedding(text: str) -> tuple:
    return tuple(model.encode(text).tolist())

# Or use a persistent cache with the database
```

## Memory Considerations

Models are loaded into RAM. For `all-MiniLM-L6-v2`:
- Model size: ~80MB
- Memory during inference: ~200MB

Load once at startup, reuse the instance.

## Device Selection

```python
# Auto-select (GPU if available)
model = SentenceTransformer("all-MiniLM-L6-v2")

# Force CPU
model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

# Force GPU
model = SentenceTransformer("all-MiniLM-L6-v2", device="cuda")
```

## Embedding Dimension

```python
# Get embedding dimension for schema definition
dim = model.get_sentence_embedding_dimension()
print(dim)  # 384 for all-MiniLM-L6-v2
```
