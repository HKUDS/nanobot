"""Tool ranking based on TF-IDF similarity to user query."""

import math
from collections import Counter
from typing import Any


class ToolRanker:
    """
    Rank tools by relevance to user query using TF-IDF.
    
    Similar to SkillRanker but optimized for tool schemas.
    """

    def __init__(self):
        self._idf_cache: dict[str, float] = {}
        self._tool_tokens_cache: dict[str, list[str]] = {}

    def rank_tools(
        self,
        user_query: str,
        tool_definitions: list[dict[str, Any]],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Rank tools by TF-IDF similarity to user query.

        Args:
            user_query: User's input text
            tool_definitions: List of tool schemas (OpenAI format)
            top_k: Number of top tools to return (0 = all tools)

        Returns:
            List of top-k tool definitions, sorted by relevance
        """
        if not user_query or not tool_definitions or top_k == 0:
            return tool_definitions

        # Tokenize query
        query_tokens = self._tokenize(user_query)
        if not query_tokens:
            return tool_definitions[:top_k]

        # Build IDF cache if needed
        if not self._idf_cache:
            self._build_idf_cache(tool_definitions)

        # Compute TF-IDF scores
        scores: list[tuple[float, dict[str, Any]]] = []
        for tool_def in tool_definitions:
            tool_name = tool_def.get("function", {}).get("name", "")
            
            # Get or cache tool tokens
            if tool_name not in self._tool_tokens_cache:
                self._tool_tokens_cache[tool_name] = self._extract_tool_tokens(tool_def)
            
            tool_tokens = self._tool_tokens_cache[tool_name]
            score = self._compute_similarity(query_tokens, tool_tokens)
            scores.append((score, tool_def))

        # Sort by score (descending) and return top-k
        scores.sort(key=lambda x: x[0], reverse=True)
        return [tool_def for _, tool_def in scores[:top_k]]

    def _extract_tool_tokens(self, tool_def: dict[str, Any]) -> list[str]:
        """Extract tokens from tool definition (name + description + parameters)."""
        func = tool_def.get("function", {})
        
        # Collect text from name, description, and parameter names/descriptions
        text_parts = [
            func.get("name", ""),
            func.get("description", ""),
        ]
        
        # Add parameter names and descriptions
        params = func.get("parameters", {}).get("properties", {})
        for param_name, param_info in params.items():
            text_parts.append(param_name)
            if isinstance(param_info, dict):
                text_parts.append(param_info.get("description", ""))
        
        full_text = " ".join(text_parts)
        return self._tokenize(full_text)

    def _build_idf_cache(self, tool_definitions: list[dict[str, Any]]) -> None:
        """Build IDF cache from all tool definitions."""
        # Count document frequency for each token
        df: Counter[str] = Counter()
        for tool_def in tool_definitions:
            tokens = self._extract_tool_tokens(tool_def)
            unique_tokens = set(tokens)
            df.update(unique_tokens)

        # Compute IDF: log(N / df)
        n_docs = len(tool_definitions)
        self._idf_cache = {
            token: math.log(n_docs / count)
            for token, count in df.items()
        }

    def _compute_similarity(self, query_tokens: list[str], tool_tokens: list[str]) -> float:
        """Compute TF-IDF cosine similarity between query and tool."""
        # Compute TF for query and tool
        query_tf = Counter(query_tokens)
        tool_tf = Counter(tool_tokens)

        # Compute TF-IDF vectors
        common_tokens = set(query_tf.keys()) & set(tool_tf.keys())
        if not common_tokens:
            return 0.0

        # Dot product of TF-IDF vectors
        dot_product = sum(
            query_tf[token] * tool_tf[token] * self._idf_cache.get(token, 1.0)
            for token in common_tokens
        )

        # Magnitude of query vector
        query_magnitude = math.sqrt(sum(
            (count * self._idf_cache.get(token, 1.0)) ** 2
            for token, count in query_tf.items()
        ))

        # Magnitude of tool vector
        tool_magnitude = math.sqrt(sum(
            (count * self._idf_cache.get(token, 1.0)) ** 2
            for token, count in tool_tf.items()
        ))

        if query_magnitude == 0 or tool_magnitude == 0:
            return 0.0

        return dot_product / (query_magnitude * tool_magnitude)

    def _tokenize(self, text: str) -> list[str]:
        """
        Tokenize text into lowercase words, filtering stop words.

        Stop words: common English words that don't carry much meaning.
        """
        stop_words = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
            "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
            "to", "was", "will", "with", "this", "or", "can", "you", "your",
        }

        # Simple word tokenization
        words = text.lower().split()
        
        # Filter: alphanumeric only, not stop words, length > 1
        return [
            word.strip(".,!?;:()[]{}\"'")
            for word in words
            if word.strip(".,!?;:()[]{}\"'").isalnum()
            and word not in stop_words
            and len(word) > 1
        ]

    def clear_cache(self) -> None:
        """Clear IDF and tool tokens cache."""
        self._idf_cache.clear()
        self._tool_tokens_cache.clear()
