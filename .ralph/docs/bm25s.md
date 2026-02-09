# bm25s Reference

bm25s is a fast BM25 implementation using Scipy sparse matrices.

## Installation

```bash
pip install bm25s

# Optional: for stemming
pip install PyStemmer
```

## Basic Usage

```python
import bm25s

# Create corpus
corpus = [
    "a cat is a feline and likes to purr",
    "a dog is the human's best friend",
    "a bird is a beautiful animal that can fly",
]

# Tokenize (returns token IDs by default)
corpus_tokens = bm25s.tokenize(corpus, stopwords="en")

# Create and index
retriever = bm25s.BM25()
retriever.index(corpus_tokens)

# Query
query = "does the cat purr?"
query_tokens = bm25s.tokenize(query, stopwords="en")

# Retrieve (returns doc indices and scores)
results, scores = retriever.retrieve(query_tokens, k=2)

# results[0, i] is the i-th result for first query
for i in range(results.shape[1]):
    doc_idx = results[0, i]
    score = scores[0, i]
    print(f"Rank {i+1}: doc {doc_idx}, score {score:.2f}")
```

## With Stemming

```python
import bm25s
import Stemmer

stemmer = Stemmer.Stemmer("english")

# Tokenize with stemmer
corpus_tokens = bm25s.tokenize(corpus, stopwords="en", stemmer=stemmer)
query_tokens = bm25s.tokenize(query, stopwords="en", stemmer=stemmer)

# Same retrieval process
retriever = bm25s.BM25()
retriever.index(corpus_tokens)
results, scores = retriever.retrieve(query_tokens, k=5)
```

## Saving and Loading

```python
# Save index
retriever.save("my_index")

# Save with corpus for convenience
retriever.save("my_index", corpus=corpus)

# Load
retriever = bm25s.BM25.load("my_index", load_corpus=True)
```

## Memory-Mapped Loading

For large indices, use memory mapping:

```python
# Load as memory-mapped (doesn't load full index into RAM)
retriever = bm25s.BM25.load("my_index", mmap=True)
```

## Multiple Queries

```python
queries = ["what is a cat?", "tell me about dogs"]
query_tokens = bm25s.tokenize(queries, stopwords="en")

# Returns shape (n_queries, k)
results, scores = retriever.retrieve(query_tokens, k=3)

# results[0] is results for first query
# results[1] is results for second query
```

## Return Documents Instead of Indices

```python
# Pass corpus to get documents directly
results = retriever.retrieve(query_tokens, corpus=corpus, k=3, return_as="documents")

# results is now the actual document strings
print(results[0, 0])  # First result for first query
```

## BM25 Variants

```python
# Different BM25 variants
retriever = bm25s.BM25(method="lucene")    # Default, Lucene's BM25
retriever = bm25s.BM25(method="robertson") # Original BM25
retriever = bm25s.BM25(method="atire")     # ATIRE variant
retriever = bm25s.BM25(method="bm25l")     # BM25L
retriever = bm25s.BM25(method="bm25+")     # BM25+
```

## Custom Tokenization

```python
from bm25s.tokenization import Tokenizer

tokenizer = Tokenizer(
    stemmer=stemmer,
    stopwords=["a", "the", "is"],
    splitter=lambda x: x.split()  # or regex pattern
)

corpus_tokens = tokenizer.tokenize(corpus)

# Get vocabulary
vocab = tokenizer.get_vocab_dict()
```

## Hybrid Search Integration

For combining with vector search:

```python
def hybrid_search(query: str, vector_results: list, bm25_retriever, corpus: list, alpha: float = 0.5):
    """
    Combine vector search and BM25 results.
    
    alpha: weight for vector scores (1-alpha for BM25)
    """
    # Get BM25 scores
    query_tokens = bm25s.tokenize(query, stopwords="en")
    bm25_results, bm25_scores = bm25_retriever.retrieve(query_tokens, k=len(corpus))
    
    # Normalize scores
    # ... combine with RRF or weighted sum
    
    return combined_results
```

## Performance Tips

1. **Pre-tokenize corpus** — tokenization is the slow part
2. **Use mmap for large indices** — saves RAM
3. **Batch queries** — process multiple queries at once
4. **Use stemming** — improves recall
5. **Save/load indices** — don't re-index every time
