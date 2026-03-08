#!/usr/bin/env python3
"""
Semantic search over unsummarized session transcripts (last 24hrs).

This script fills the gap between real-time conversation and diary entries:
- Diary entries are already summarized (covered by load-context-semantic.py)
- Very recent sessions (< 24hrs) aren't in diary yet
- This script searches raw session transcripts to catch fresh context

Features:
- Finds sessions started in last 24hrs that aren't yet in diary
- Smart caching: .unsummarized-embeddings/{session_id}.json
  - Cache HIT: use stored embeddings (instant ~100ms)
  - Cache MISS: generate via Ollama qwen3-embedding (~2-3s)
- In-memory vector search across cached chunks
- Returns top K matches formatted like load-context-semantic.py

Integration:
- Called during AGENTS.md startup (Step 3) alongside load-context-semantic.py
- Cleanup: rollup-daily.py deletes cache for summarized sessions

Performance:
- First search per session: ~2-3s (embedding generation)
- Cached searches: <100ms
- Storage: ~1-2KB per session

Usage:
    python3 scripts/search-unsummarized.py "secret word from recent session"
    python3 scripts/search-unsummarized.py --query "what did we discuss" --top-k 5
"""

import sys
import json
import argparse
import hashlib
import re
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Ollama for local embeddings
import urllib.request
import urllib.parse
import numpy as np

SESSIONS_DIR = Path.home() / ".clawdbot/agents/main/sessions"
STATE_FILE = Path("memory/diary/2026/.state.json")
CACHE_DIR = Path(".unsummarized-embeddings")
EMBEDDING_MODEL = "qwen3-embedding"
OLLAMA_HOST = "http://localhost:11434"

# Chunk size for session transcripts (~200 words)
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150


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


def cosine_similarity(vec1, vec2):
    """Calculate cosine similarity between two vectors."""
    vec1 = np.array(vec1)
    vec2 = np.array(vec2)
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))


def chunk_text(text, overlap=CHUNK_OVERLAP):
    """Split text into chunks with overlap."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        if len(current_chunk) + len(para) > CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk.strip())
            # Overlap: last few words
            words = current_chunk.split()
            overlap_words = words[-20:] if len(words) > 20 else words
            current_chunk = " ".join(overlap_words) + "\n\n" + para
        else:
            current_chunk += "\n\n" + para if current_chunk else para
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def load_state():
    """Load .state.json to get last summarized session ID."""
    if not STATE_FILE.exists():
        return None
    
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
            return state.get('lastSummarizedSessionId')
    except:
        return None


def find_unsummarized_sessions(hours=24):
    """
    Find sessions started in last N hours that aren't yet summarized.
    
    Returns: List of (session_id, start_time, filepath)
    """
    last_summarized = load_state()
    cutoff = datetime.now(ZoneInfo("UTC")) - timedelta(hours=hours)
    
    # Get timestamp of last summarized session for comparison
    last_summarized_time = None
    if last_summarized:
        last_summarized_file = SESSIONS_DIR / f"{last_summarized}.jsonl"
        if last_summarized_file.exists():
            try:
                with open(last_summarized_file) as f:
                    first_line = f.readline()
                    session_meta = json.loads(first_line)
                    timestamp = session_meta.get('timestamp')
                    if timestamp:
                        last_summarized_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except:
                pass
    
    unsummarized = []
    
    # Scan session files
    for session_file in SESSIONS_DIR.glob("*.jsonl"):
        # Skip deleted sessions
        if ".deleted." in session_file.name:
            continue
        
        # Skip lock files
        if session_file.name.endswith(".lock"):
            continue
        
        session_id = session_file.stem
        
        # Read first line to get session start time
        try:
            with open(session_file) as f:
                first_line = f.readline()
                session_meta = json.loads(first_line)
                
                timestamp = session_meta.get('timestamp')
                if not timestamp:
                    continue
                
                start_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                
                # Check if within time window
                if start_time < cutoff:
                    continue
                
                # Check if already summarized (by timestamp comparison)
                if last_summarized_time and start_time <= last_summarized_time:
                    continue
                
                unsummarized.append((session_id, start_time, session_file))
        
        except Exception as e:
            print(f"Warning: Error reading {session_file.name}: {e}", file=sys.stderr)
            continue
    
    # Sort by start time (oldest first)
    unsummarized.sort(key=lambda x: x[1])
    
    return unsummarized


def extract_session_text(session_file):
    """
    Extract meaningful text from session JSONL.
    
    Returns: Dictionary with metadata and transcript text
    """
    try:
        with open(session_file) as f:
            lines = f.readlines()
        
        # Parse session metadata
        session_meta = json.loads(lines[0])
        session_id = session_meta['id']
        start_ts = datetime.fromisoformat(session_meta['timestamp'].replace('Z', '+00:00'))
        
        # Extract messages
        user_messages = []
        assistant_messages = []
        
        for line in lines[1:]:
            try:
                entry = json.loads(line)
                if entry.get("type") == "message":
                    msg = entry.get("message", {})
                    role = msg.get("role")
                    content = msg.get("content", [])
                    
                    if role == "user" and content:
                        text = content[0].get("text", "")
                        # Skip heartbeat polls
                        if text and not text.startswith("Read HEARTBEAT.md"):
                            user_messages.append(text)
                    
                    elif role == "assistant":
                        for item in content:
                            if item.get("type") == "text":
                                assistant_messages.append(item.get("text", ""))
            except:
                continue
        
        # Build transcript
        mst = ZoneInfo('America/Edmonton')
        start_mst = start_ts.astimezone(mst)
        
        transcript = f"Session {session_id[:8]} ({start_mst.strftime('%Y-%m-%d %H:%M')} MST)\n\n"
        
        # Interleave user and assistant messages
        max_len = max(len(user_messages), len(assistant_messages))
        for i in range(max_len):
            if i < len(user_messages):
                transcript += f"User: {user_messages[i]}\n\n"
            if i < len(assistant_messages):
                # Truncate very long assistant messages
                assistant_text = assistant_messages[i]
                if len(assistant_text) > 1000:
                    assistant_text = assistant_text[:1000] + "..."
                transcript += f"Assistant: {assistant_text}\n\n"
        
        return {
            'session_id': session_id,
            'start_time': start_mst.isoformat(),
            'transcript': transcript
        }
    
    except Exception as e:
        print(f"Error extracting session text: {e}", file=sys.stderr)
        return None


def get_cached_embeddings(session_id):
    """Load cached embeddings for a session."""
    cache_file = CACHE_DIR / f"{session_id}.json"
    
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file) as f:
            return json.load(f)
    except:
        return None


def save_cached_embeddings(session_id, chunks, embeddings, metadata):
    """Save embeddings to cache."""
    CACHE_DIR.mkdir(exist_ok=True)
    
    cache_file = CACHE_DIR / f"{session_id}.json"
    cache_data = {
        'session_id': session_id,
        'chunks': chunks,
        'embeddings': embeddings,
        'metadata': metadata,
        'cached_at': datetime.now(ZoneInfo("America/Edmonton")).isoformat()
    }
    
    with open(cache_file, 'w') as f:
        json.dump(cache_data, f)


def embed_session(session_data):
    """
    Chunk session text and generate embeddings.
    Uses cache if available, otherwise generates and caches.
    
    Returns: List of (chunk_text, embedding, metadata)
    """
    session_id = session_data['session_id']
    
    # Check cache
    cached = get_cached_embeddings(session_id)
    if cached:
        print(f"  Cache HIT: {session_id[:8]}", file=sys.stderr)
        results = []
        for chunk, embedding in zip(cached['chunks'], cached['embeddings']):
            results.append((chunk, embedding, cached['metadata']))
        return results
    
    print(f"  Cache MISS: {session_id[:8]} - generating embeddings...", file=sys.stderr)
    
    # Chunk transcript
    chunks = chunk_text(session_data['transcript'])
    
    # Generate embeddings
    embeddings = []
    for chunk in chunks:
        embedding = get_embedding(chunk)
        if embedding is None:
            print(f"  Warning: Failed to embed chunk", file=sys.stderr)
            continue
        embeddings.append(embedding)
    
    # Save to cache
    metadata = {
        'session_id': session_id,
        'start_time': session_data['start_time']
    }
    save_cached_embeddings(session_id, chunks, embeddings, metadata)
    
    # Return results
    results = []
    for chunk, embedding in zip(chunks, embeddings):
        results.append((chunk, embedding, metadata))
    
    return results


def search_unsummarized(query, top_k=10, min_score=0.3, hours=24):
    """
    Search unsummarized sessions for relevant content.
    
    Args:
        query: Search query
        top_k: Number of results to return
        min_score: Minimum similarity threshold
        hours: Look back N hours for unsummarized sessions
    
    Returns:
        List of (chunk_text, metadata, similarity_score)
    """
    # Find unsummarized sessions
    sessions = find_unsummarized_sessions(hours=hours)
    
    if not sessions:
        print("No unsummarized sessions found in last 24hrs", file=sys.stderr)
        return []
    
    print(f"Found {len(sessions)} unsummarized sessions", file=sys.stderr)
    
    # Get query embedding
    query_embedding = get_embedding(query)
    if query_embedding is None:
        print("Error: Failed to generate query embedding", file=sys.stderr)
        return []
    
    # Collect all chunks and embeddings from all sessions
    all_chunks = []
    
    for session_id, start_time, session_file in sessions:
        # Extract session text
        session_data = extract_session_text(session_file)
        if not session_data:
            continue
        
        # Embed session (with caching)
        chunks = embed_session(session_data)
        all_chunks.extend(chunks)
    
    # Search across all chunks
    results = []
    for chunk_text, chunk_embedding, metadata in all_chunks:
        similarity = cosine_similarity(query_embedding, chunk_embedding)
        
        if similarity >= min_score:
            results.append((chunk_text, metadata, similarity))
    
    # Sort by similarity (highest first)
    results.sort(key=lambda x: x[2], reverse=True)
    
    # Return top K
    return results[:top_k]


def format_output(results, query=None):
    """Format search results for context injection."""
    if not results:
        return "=== UNSUMMARIZED SESSION SEARCH ===\n(No relevant content found)\n"
    
    sections = []
    
    # Header
    header = "=== UNSUMMARIZED SESSION CONTEXT ==="
    if query:
        header += f"\nQuery: {query}"
    header += f"\nFound {len(results)} relevant chunks from recent sessions\n"
    sections.append(header)
    
    # Group by session
    by_session = {}
    for chunk, metadata, score in results:
        session_id = metadata.get('session_id', 'unknown')
        if session_id not in by_session:
            by_session[session_id] = []
        by_session[session_id].append({
            'chunk': chunk,
            'metadata': metadata,
            'score': score
        })
    
    # Format each session
    for session_id, chunks in sorted(by_session.items(), key=lambda x: max(c['score'] for c in x[1]), reverse=True):
        start_time = chunks[0]['metadata'].get('start_time', 'unknown')
        
        section = f"\n--- Session {session_id[:8]} ({start_time}) ---"
        
        for chunk_data in sorted(chunks, key=lambda x: x['score'], reverse=True):
            chunk_text = chunk_data['chunk']
            score = chunk_data['score']
            
            section += f"\n[Relevance: {score:.3f}]\n"
            section += chunk_text + "\n"
        
        sections.append(section)
    
    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser(
        description="Search unsummarized sessions for relevant content",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search for secret word
  python3 scripts/search-unsummarized.py "secret word from recent session"
  
  # Search with adjustable threshold
  python3 scripts/search-unsummarized.py --query "what did we discuss" --min-score 0.4
  
  # Look back further (48 hours)
  python3 scripts/search-unsummarized.py "recent work" --hours 48
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
        '--hours',
        type=int,
        default=24,
        help='Look back N hours for unsummarized sessions (default: 24)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )
    
    args = parser.parse_args()
    
    # Get query
    if args.query:
        query = args.query
    elif args.query_words:
        query = ' '.join(args.query_words)
    else:
        query = "recent conversation topics and context"
    
    # Search
    results = search_unsummarized(
        query=query,
        top_k=args.top_k,
        min_score=args.min_score,
        hours=args.hours
    )
    
    # Output
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
        print(format_output(results, query=query))


if __name__ == "__main__":
    main()
