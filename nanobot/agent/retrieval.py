"""Lightweight memory retrieval using BM25."""

import re
from typing import List, Tuple
from rank_bm25 import BM25Okapi

def tokenize(text: str) -> List[str]:
    """
    Simple tokenizer for BM25.
    Lowercases and extracts alphanumeric words.
    """
    return re.findall(r'\w+', text.lower())

class MemoryRetriever:
    """
    Handles retrieval of relevant memory chunks using BM25.
    """
    
    def __init__(self, chunks: List[str]):
        self.chunks = chunks
        self.tokenized_corpus = [tokenize(chunk) for chunk in chunks]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def retrieve(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """
        Retrieve top-k relevant chunks for a given query.
        """
        if not self.chunks:
            return []
            
        tokenized_query = tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        
        # Combine chunks with their scores
        chunk_scores = list(zip(self.chunks, scores))
        
        # Sort by score descending and take top_k
        sorted_results = sorted(chunk_scores, key=lambda x: x[1], reverse=True)
        
        # Filter out zero scores to ensure relevance
        relevant_results = [res for res in sorted_results[:top_k] if res[1] > 0]
        
        return relevant_results

def split_markdown_into_chunks(content: str, max_chunk_size: int = 1000) -> List[str]:
    """
    Split markdown content into semantic chunks.
    Prioritizes splitting by headers, then by double newlines.
    """
    if not content:
        return []

    # Split by headers (h1, h2, h3) but keep the headers with the content
    # This regex looks for a newline followed by a header
    raw_chunks = re.split(r'\n(?=#+ )', content)
    
    final_chunks = []
    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
            
        # If a chunk is still too large, split it by double newlines
        if len(chunk) > max_chunk_size:
            sub_chunks = chunk.split('\n\n')
            current_sub_chunk = ""
            
            for sub in sub_chunks:
                if len(current_sub_chunk) + len(sub) < max_chunk_size:
                    current_sub_chunk += ("\n\n" if current_sub_chunk else "") + sub
                else:
                    if current_sub_chunk:
                        final_chunks.append(current_sub_chunk.strip())
                    current_sub_chunk = sub
            
            if current_sub_chunk:
                final_chunks.append(current_sub_chunk.strip())
        else:
            final_chunks.append(chunk)
            
    return final_chunks
