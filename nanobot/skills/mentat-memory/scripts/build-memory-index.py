#!/usr/bin/env python3
"""
Build memory index for semantic search.
Scans memory files, chunks text, embeds with qwen3-embedding, stores in ChromaDB.
"""

import os
import sys
import re
import glob
import json
from pathlib import Path
from datetime import datetime
import hashlib

# Add whisper-venv to path for chromadb
sys.path.insert(0, '/home/deva/.whisper-venv/lib/python3.12/site-packages')

import chromadb
from chromadb.config import Settings

# Ollama API for embeddings
import urllib.request
import urllib.parse

VECTOR_DB_PATH = "/home/deva/.memory-vectors"
WORKSPACE = "/home/deva/shared"
EMBEDDING_MODEL = "qwen3-embedding"
OLLAMA_HOST = "http://localhost:11434"

# Memory file patterns to index
MEMORY_PATTERNS = [
    "memory/diary/2026/daily/*.md",
    "memory/diary/2026/weekly/*.md",
    "memory/diary/2026/monthly/*.md",
    "memory/diary/2026/annual.md",
    "memory/sticky-notes/**/*.md",
    "MEMORY.md",
]

# Chunk size (~200-300 words)
CHUNK_SIZE = 1500  # ~250 words at 6 chars/word
CHUNK_OVERLAP = 200  # Preserve context between chunks


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


def chunk_text(text, source_file):
    """Split text into chunks with overlap, preserving context."""
    # Split by paragraphs first
    paragraphs = re.split(r'\n\s*\n', text)
    
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        # If adding this paragraph exceeds chunk size, save current chunk
        if len(current_chunk) + len(para) > CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk.strip())
            # Start new chunk with overlap (last few words of previous chunk)
            words = current_chunk.split()
            overlap_words = words[-30:] if len(words) > 30 else words
            current_chunk = " ".join(overlap_words) + "\n\n" + para
        else:
            current_chunk += "\n\n" + para if current_chunk else para
    
    # Add final chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def extract_date_from_path(filepath):
    """Extract date from filepath (e.g., 2026-01-15 from diary/2026/daily/2026-01-15.md)."""
    # Try to find YYYY-MM-DD pattern
    match = re.search(r'(\d{4}-\d{2}-\d{2})', filepath)
    if match:
        return match.group(1)
    
    # Try to find YYYY-Wnn pattern (week)
    match = re.search(r'(\d{4}-W\d{2})', filepath)
    if match:
        return match.group(1)
    
    # Try to find YYYY-MM pattern (month)
    match = re.search(r'/(\d{4}-\d{2})\.md', filepath)
    if match:
        return match.group(1)
    
    # Try to find YYYY (annual)
    match = re.search(r'/(\d{4})/annual\.md', filepath)
    if match:
        return f"{match.group(1)}-annual"
    
    return None


def build_index():
    """Scan memory files, chunk, embed, and store in ChromaDB."""
    print(f"Building memory index...")
    print(f"Vector DB: {VECTOR_DB_PATH}")
    print(f"Embedding model: {EMBEDDING_MODEL}")
    print()
    
    # Initialize ChromaDB
    client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
    
    # Delete existing collection if it exists
    try:
        client.delete_collection("memory")
        print("Deleted existing memory collection")
    except:
        pass
    
    # Create new collection
    collection = client.create_collection(
        name="memory",
        metadata={"description": "Memory embedding index for semantic search"}
    )
    
    # Collect all files to index
    all_files = []
    os.chdir(WORKSPACE)
    
    for pattern in MEMORY_PATTERNS:
        files = glob.glob(pattern, recursive=True)
        all_files.extend(files)
    
    print(f"Found {len(all_files)} files to index")
    print()
    
    total_chunks = 0
    files_indexed = 0
    
    for filepath in sorted(all_files):
        if not os.path.exists(filepath):
            continue
        
        print(f"Indexing: {filepath}")
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Skip empty files
            if not content.strip():
                print(f"  Skipped (empty)")
                continue
            
            # Extract date from filepath
            date = extract_date_from_path(filepath)
            
            # Chunk the text
            chunks = chunk_text(content, filepath)
            print(f"  Created {len(chunks)} chunks")
            
            # Embed and store each chunk
            for i, chunk in enumerate(chunks):
                # Generate unique ID for this chunk
                chunk_id = hashlib.md5(f"{filepath}:{i}".encode()).hexdigest()
                
                # Get embedding
                embedding = get_embedding(chunk)
                
                # Store in ChromaDB
                collection.add(
                    ids=[chunk_id],
                    embeddings=[embedding],
                    documents=[chunk],
                    metadatas=[{
                        "source_file": filepath,
                        "date": date or "unknown",
                        "chunk_id": i,
                        "total_chunks": len(chunks)
                    }]
                )
                
                total_chunks += 1
            
            files_indexed += 1
            
        except Exception as e:
            print(f"  Error: {e}")
            continue
    
    print()
    print(f"✅ Index built successfully!")
    print(f"   Files indexed: {files_indexed}")
    print(f"   Total chunks: {total_chunks}")
    print(f"   Vector DB location: {VECTOR_DB_PATH}")


if __name__ == "__main__":
    build_index()
