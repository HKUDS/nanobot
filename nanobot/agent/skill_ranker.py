"""TF-IDF based skill relevance ranking."""

import math
import re
from collections import Counter
from pathlib import Path


class SkillRanker:
    """
    Ranks skills by relevance to user query using TF-IDF.
    
    This allows dynamic skill injection - only the most relevant skills
    are fully loaded into context, saving significant tokens.
    """

    def __init__(self, skills_loader):
        """
        Initialize ranker with skills loader.
        
        Args:
            skills_loader: SkillsLoader instance
        """
        self.skills_loader = skills_loader
        self._idf_cache = {}
        self._skill_tokens_cache = {}

    def rank_skills(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """
        Rank skills by relevance to query using TF-IDF.
        
        Args:
            query: User query text
            top_k: Number of top skills to return
            
        Returns:
            List of (skill_name, score) tuples, sorted by score descending
        """
        if not query or not query.strip():
            return []

        # Get all available skills
        all_skills = self.skills_loader.list_skills(filter_unavailable=True)
        if not all_skills:
            return []

        # Tokenize query
        query_tokens = self._tokenize(query.lower())
        if not query_tokens:
            return []

        # Build IDF if not cached
        if not self._idf_cache:
            self._build_idf(all_skills)

        # Score each skill
        scores = []
        for skill in all_skills:
            name = skill["name"]
            score = self._compute_tfidf_score(name, query_tokens)
            if score > 0:
                scores.append((name, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        return scores[:top_k]

    def _tokenize(self, text: str) -> list[str]:
        """
        Tokenize text into words.
        
        Args:
            text: Input text
            
        Returns:
            List of tokens (lowercase, alphanumeric only)
        """
        # Remove special chars, split on whitespace
        tokens = re.findall(r'\b[a-z0-9]+\b', text.lower())
        # Remove common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'what', 'which', 'who', 'when', 'where', 'why', 'how'}
        return [t for t in tokens if t not in stop_words and len(t) > 2]

    def _get_skill_tokens(self, skill_name: str) -> list[str]:
        """
        Get tokens from skill content (cached).
        
        Args:
            skill_name: Name of skill
            
        Returns:
            List of tokens from skill content
        """
        if skill_name in self._skill_tokens_cache:
            return self._skill_tokens_cache[skill_name]

        content = self.skills_loader.load_skill(skill_name)
        if not content:
            self._skill_tokens_cache[skill_name] = []
            return []

        # Include skill name, description, and content
        meta = self.skills_loader.get_skill_metadata(skill_name) or {}
        desc = meta.get("description", "")
        
        full_text = f"{skill_name} {desc} {content}".lower()
        tokens = self._tokenize(full_text)
        
        self._skill_tokens_cache[skill_name] = tokens
        return tokens

    def _build_idf(self, skills: list[dict]):
        """
        Build IDF (Inverse Document Frequency) for all terms.
        
        Args:
            skills: List of skill dicts
        """
        # Count document frequency for each term
        df = Counter()
        total_docs = len(skills)

        for skill in skills:
            name = skill["name"]
            tokens = self._get_skill_tokens(name)
            # Count unique tokens in this document
            unique_tokens = set(tokens)
            for token in unique_tokens:
                df[token] += 1

        # Compute IDF: log(N / df)
        self._idf_cache = {}
        for term, freq in df.items():
            self._idf_cache[term] = math.log(total_docs / freq)

    def _compute_tfidf_score(self, skill_name: str, query_tokens: list[str]) -> float:
        """
        Compute TF-IDF cosine similarity between query and skill.
        
        Args:
            skill_name: Name of skill
            query_tokens: Tokenized query
            
        Returns:
            TF-IDF score (0.0 to 1.0)
        """
        skill_tokens = self._get_skill_tokens(skill_name)
        if not skill_tokens:
            return 0.0

        # Compute TF for skill
        skill_tf = Counter(skill_tokens)
        skill_total = len(skill_tokens)

        # Compute TF for query
        query_tf = Counter(query_tokens)
        query_total = len(query_tokens)

        # Compute TF-IDF vectors
        all_terms = set(skill_tf.keys()) | set(query_tf.keys())
        
        skill_vector = []
        query_vector = []
        
        for term in all_terms:
            idf = self._idf_cache.get(term, 0)
            
            # Skill TF-IDF
            tf_skill = skill_tf.get(term, 0) / skill_total if skill_total > 0 else 0
            skill_vector.append(tf_skill * idf)
            
            # Query TF-IDF
            tf_query = query_tf.get(term, 0) / query_total if query_total > 0 else 0
            query_vector.append(tf_query * idf)

        # Cosine similarity
        dot_product = sum(s * q for s, q in zip(skill_vector, query_vector))
        skill_norm = math.sqrt(sum(s * s for s in skill_vector))
        query_norm = math.sqrt(sum(q * q for q in query_vector))

        if skill_norm == 0 or query_norm == 0:
            return 0.0

        return dot_product / (skill_norm * query_norm)
