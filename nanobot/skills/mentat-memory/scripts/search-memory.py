#!/usr/bin/env python3
"""
Search memory using semantic embeddings.
Takes a query, embeds it, searches ChromaDB, and summarizes results with local LLM.
"""

import sys
import json
import urllib.request
import urllib.parse
import time

# Add whisper-venv to path for chromadb
sys.path.insert(0, '/home/deva/.whisper-venv/lib/python3.12/site-packages')

import chromadb

VECTOR_DB_PATH = "/home/deva/.memory-vectors"
EMBEDDING_MODEL = "qwen3-embedding"
SUMMARIZER_MODEL = "granite4:3b"  # Fast local model
OLLAMA_HOST = "http://localhost:11434"
TOP_K_RESULTS = 10


def get_embedding(text):
    """Get embedding from Ollama qwen3-embedding model."""
    url = f"{OLLAMA_HOST}/api/embeddings"
    data = json.dumps({
        "model": EMBEDDING_MODEL,
        "prompt": text
    }).encode('utf-8')
    
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode())
        return result['embedding']


def generate_summary(query, results):
    """Generate summary using local Ollama model."""
    # Build context from results
    context_parts = []
    for i, (doc, metadata) in enumerate(results):
        source = metadata.get('source_file', 'unknown')
        date = metadata.get('date', 'unknown')
        context_parts.append(f"[Source: {source} | Date: {date}]\n{doc}\n")
    
    context = "\n---\n".join(context_parts)
    
    prompt = f"""Based on these memory excerpts, answer the question: {query}

Memory excerpts:
{context}

Instructions:
- Provide a concise, factual answer based on the excerpts
- Cite sources when relevant (mention file names or dates)
- If the excerpts don't contain enough information, say so
- Be direct and helpful

Answer:"""
    
    url = f"{OLLAMA_HOST}/api/generate"
    data = json.dumps({
        "model": SUMMARIZER_MODEL,
        "prompt": prompt,
        "stream": False
    }).encode('utf-8')
    
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode())
        return result['response']


def search_memory(query):
    """Search memory with semantic search."""
    start_time = time.time()
    
    print(f"🔍 Searching memory: '{query}'", file=sys.stderr)
    print(file=sys.stderr)
    
    # Connect to ChromaDB
    t0 = time.time()
    try:
        client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
        collection = client.get_collection("memory")
    except Exception as e:
        print(f"❌ Error: Could not load memory index: {e}", file=sys.stderr)
        print(f"   Run: python3 scripts/build-memory-index.py", file=sys.stderr)
        return None
    
    # Get query embedding
    t1 = time.time()
    print(f"⚡ Embedding query with {EMBEDDING_MODEL}...", file=sys.stderr)
    query_embedding = get_embedding(query)
    embed_time = time.time() - t1
    
    # Search ChromaDB
    t2 = time.time()
    print(f"🔎 Searching {collection.count()} memory chunks...", file=sys.stderr)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=TOP_K_RESULTS
    )
    search_time = time.time() - t2
    
    if not results['documents'] or not results['documents'][0]:
        print(f"❌ No results found", file=sys.stderr)
        return None
    
    # Extract documents and metadata
    docs = results['documents'][0]
    metadatas = results['metadatas'][0]
    distances = results['distances'][0]
    
    print(f"✅ Found {len(docs)} relevant chunks", file=sys.stderr)
    print(file=sys.stderr)
    
    # Show top results
    print(f"Top results:", file=sys.stderr)
    for i, (doc, metadata, distance) in enumerate(zip(docs[:5], metadatas[:5], distances[:5])):
        source = metadata.get('source_file', 'unknown')
        date = metadata.get('date', 'unknown')
        preview = doc[:100].replace('\n', ' ') + '...' if len(doc) > 100 else doc.replace('\n', ' ')
        print(f"{i+1}. {source} [{date}] (similarity: {1-distance:.3f})", file=sys.stderr)
        print(f"   {preview}", file=sys.stderr)
    print(file=sys.stderr)
    
    # Generate summary
    t3 = time.time()
    print(f"🤖 Generating summary with {SUMMARIZER_MODEL}...", file=sys.stderr)
    print(file=sys.stderr)
    
    summary = generate_summary(query, list(zip(docs, metadatas)))
    summary_time = time.time() - t3
    
    total_time = time.time() - start_time
    
    print(f"⏱️  Timing breakdown:", file=sys.stderr)
    print(f"   Embedding:     {embed_time:.2f}s", file=sys.stderr)
    print(f"   Search:        {search_time:.3f}s", file=sys.stderr)
    print(f"   Summary (LLM): {summary_time:.2f}s", file=sys.stderr)
    print(f"   Total:         {total_time:.2f}s", file=sys.stderr)
    print(file=sys.stderr)
    
    return summary


def main():
    if len(sys.argv) < 2:
        print("Usage: search-memory.py <query>", file=sys.stderr)
        print("Example: search-memory.py 'What did we do with Sandman?'", file=sys.stderr)
        sys.exit(1)
    
    query = " ".join(sys.argv[1:])
    
    result = search_memory(query)
    
    if result:
        print("="*60)
        print(result)
        print("="*60)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
