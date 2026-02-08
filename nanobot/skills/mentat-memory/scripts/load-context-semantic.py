#!/usr/bin/env python3
"""
Semantic memory context loader using vector search.

This script loads diary context using semantic similarity instead of naive chronological reading.
Accepts a query parameter (current user message or session context) and returns relevant memory
snippets ranked by relevance.

Usage:
    python3 scripts/load-context-semantic.py "query text here"
    python3 scripts/load-context-semantic.py --query "query text" --top-k 10 --min-score 0.3

Integration with OpenClaw:
    Can be used as an alternative to load-context.py during startup, or invoked on-demand
    when the agent needs to recall specific information.
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# Add whisper-venv to path for chromadb (local vector DB)
sys.path.insert(0, '/home/deva/.whisper-venv/lib/python3.12/site-packages')

try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("Warning: ChromaDB not available. Install with: pip install chromadb", file=sys.stderr)

# Ollama for local embeddings
import urllib.request
import urllib.parse

VECTOR_DB_PATH = "/home/deva/.memory-vectors"
EMBEDDING_MODEL = "qwen3-embedding"  # Local Ollama model
OLLAMA_HOST = "http://localhost:11434"


def get_embedding(text):
    """Get embedding from Ollama qwen3-embedding model."""
    url = f"{OLLAMA_HOST}/api/embeddings"
    data = json.dumps({
        "model": EMBEDDING_MODEL,
        "prompt": text
    }).encode('utf-8')
    
    try:
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            return result['embedding']
    except Exception as e:
        print(f"Error getting embedding: {e}", file=sys.stderr)
        return None


def semantic_search(query, top_k=10, min_score=0.0):
    """
    Search memory using semantic similarity.
    
    Args:
        query: Natural language query (e.g., "recent decisions about memory system")
        top_k: Number of results to return
        min_score: Minimum similarity score (0.0-1.0)
        
    Returns:
        List of tuples: (chunk_text, metadata, similarity_score)
    """
    if not CHROMADB_AVAILABLE:
        print("ChromaDB not available. Falling back to chronological loading.", file=sys.stderr)
        return None
    
    # Connect to ChromaDB
    try:
        client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
        collection = client.get_collection("memory")
    except Exception as e:
        print(f"Error loading memory index: {e}", file=sys.stderr)
        print(f"Build index with: python3 scripts/build-memory-index.py", file=sys.stderr)
        return None
    
    # Get query embedding
    query_embedding = get_embedding(query)
    if query_embedding is None:
        return None
    
    # Search ChromaDB
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
    except Exception as e:
        print(f"Error searching memory: {e}", file=sys.stderr)
        return None
    
    if not results['documents'] or not results['documents'][0]:
        return []
    
    # Extract and filter results
    docs = results['documents'][0]
    metadatas = results['metadatas'][0]
    distances = results['distances'][0]
    
    # Convert distance to similarity score (1 - normalized_distance)
    # ChromaDB uses L2 distance, so we need to convert to similarity
    search_results = []
    for doc, metadata, distance in zip(docs, metadatas, distances):
        similarity = 1.0 - (distance / 2.0)  # Normalize L2 distance to 0-1 range
        
        if similarity >= min_score:
            search_results.append((doc, metadata, similarity))
    
    return search_results


def format_context_output(results, query=None):
    """
    Format search results as context suitable for agent loading.
    
    Args:
        results: List of (chunk_text, metadata, similarity_score) tuples
        query: Original query (for header)
        
    Returns:
        Formatted string suitable for context injection
    """
    if not results:
        return "=== SEMANTIC SEARCH RESULTS ===\n(No relevant context found)\n"
    
    sections = []
    
    # Header
    header = "=== SEMANTIC MEMORY CONTEXT ==="
    if query:
        header += f"\nQuery: {query}"
    header += f"\nFound {len(results)} relevant memory chunks\n"
    sections.append(header)
    
    # Group results by source file for better readability
    by_source = {}
    for chunk, metadata, score in results:
        source = metadata.get('source_file', 'unknown')
        date = metadata.get('date', 'unknown')
        
        if source not in by_source:
            by_source[source] = []
        
        by_source[source].append({
            'chunk': chunk,
            'date': date,
            'score': score
        })
    
    # Format each source group
    for source, chunks in sorted(by_source.items(), key=lambda x: max(c['score'] for c in x[1]), reverse=True):
        source_section = f"\n--- {source} ---"
        
        for chunk_data in sorted(chunks, key=lambda x: x['score'], reverse=True):
            chunk_text = chunk_data['chunk']
            date = chunk_data['date']
            score = chunk_data['score']
            
            # Add metadata header for chunk
            source_section += f"\n[Date: {date} | Relevance: {score:.3f}]\n"
            source_section += chunk_text + "\n"
        
        sections.append(source_section)
    
    return "\n".join(sections)


def chronological_fallback():
    """
    Fallback to chronological loading when vector search is unavailable.
    Same behavior as original load-context.py
    """
    now = datetime.now(ZoneInfo("America/Edmonton"))
    year = now.year
    month = now.strftime("%Y-%m")
    week = now.strftime("%Y-W%V")
    day = now.strftime("%Y-%m-%d")
    
    base = Path("memory/diary") / str(year)
    sections = []
    
    # Load in attention-optimized order
    daily_path = base / "daily" / f"{day}.md"
    if daily_path.exists():
        sections.append(f"=== TODAY ({day}) ===\n{daily_path.read_text()}\n")
    
    weekly_path = base / "weekly" / f"{week}.md"
    if weekly_path.exists():
        sections.append(f"=== THIS WEEK ({week}) ===\n{weekly_path.read_text()}\n")
    
    monthly_path = base / "monthly" / f"{month}.md"
    if monthly_path.exists():
        sections.append(f"=== THIS MONTH ({month}) ===\n{monthly_path.read_text()}\n")
    
    annual_path = base / "annual.md"
    if annual_path.exists():
        sections.append(f"=== THIS YEAR ({year}) ===\n{annual_path.read_text()}\n")
    
    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser(
        description="Load memory context using semantic search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search for specific topic
  python3 scripts/load-context-semantic.py "decisions about memory system"
  
  # Use current message as query
  python3 scripts/load-context-semantic.py "what was the secret word?"
  
  # Adjust relevance threshold
  python3 scripts/load-context-semantic.py --query "sandman implementation" --min-score 0.5
  
  # Fallback to chronological
  python3 scripts/load-context-semantic.py --chronological
        """
    )
    
    parser.add_argument(
        'query_words',
        nargs='*',
        help='Query text (can also use --query flag)'
    )
    parser.add_argument(
        '--query',
        help='Query text (alternative to positional args)'
    )
    parser.add_argument(
        '--top-k',
        type=int,
        default=10,
        help='Number of results to return (default: 10)'
    )
    parser.add_argument(
        '--min-score',
        type=float,
        default=0.3,
        help='Minimum similarity score 0.0-1.0 (default: 0.3)'
    )
    parser.add_argument(
        '--chronological',
        action='store_true',
        help='Force chronological fallback mode'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )
    
    args = parser.parse_args()
    
    # Get query from either positional args or --query flag
    if args.query:
        query = args.query
    elif args.query_words:
        query = ' '.join(args.query_words)
    else:
        # No query provided - load recent context as default
        query = "recent work, decisions, and active projects"
    
    # Force chronological mode if requested
    if args.chronological:
        print(chronological_fallback())
        return
    
    # Try semantic search
    results = semantic_search(query, top_k=args.top_k, min_score=args.min_score)
    
    if results is None:
        # Vector search failed, fall back to chronological
        print("Falling back to chronological loading...", file=sys.stderr)
        print(chronological_fallback())
        return
    
    # Output results
    if args.json:
        json_output = {
            'query': query,
            'results': [
                {
                    'text': chunk,
                    'metadata': metadata,
                    'score': score
                }
                for chunk, metadata, score in results
            ]
        }
        print(json.dumps(json_output, indent=2))
    else:
        print(format_context_output(results, query=query))


if __name__ == "__main__":
    main()
