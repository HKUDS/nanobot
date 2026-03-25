"""Graph augmentation — entity collection and context line generation.

``GraphAugmenter`` owns the graph-related stages of the retrieval pipeline:
collecting entity names from the knowledge graph and event triples, extracting
query entities via index lookup, and building formatted context lines for
prompt assembly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..graph.graph import KnowledgeGraph
    from ..write.extractor import MemoryExtractor


class GraphAugmenter:
    """Owns graph entity collection and context line generation."""

    def __init__(
        self,
        *,
        graph: KnowledgeGraph | None,
        extractor: MemoryExtractor | None = None,
        read_events_fn: Callable[..., list[dict[str, Any]]],
    ) -> None:
        self._graph = graph
        self._extractor = extractor
        self._read_events_fn = read_events_fn
        self._graph_cache: dict[frozenset[str], set[str]] = {}

    def reset_cache(self) -> None:
        """Clear the per-request graph entity cache."""
        self._graph_cache = {}

    # ------------------------------------------------------------------
    # Entity collection
    # ------------------------------------------------------------------

    def collect_graph_entity_names(
        self,
        query: str,
        events: list[dict[str, Any]],
    ) -> set[str]:
        """Collect entity names related to query entities via graph and event triples."""
        if self._graph is None or not self._graph.enabled:
            return set()

        query_entities = (
            {e.lower() for e in self._extractor._extract_entities(query)}
            if self._extractor is not None
            else set()
        )
        if not query_entities:
            return set()

        cache_key = frozenset(query_entities)
        if cache_key in self._graph_cache:
            return self._graph_cache[cache_key]

        graph_entity_names: set[str] = set()
        # Collect from event triples
        for evt in events:
            for triple in evt.get("triples") or []:
                subj = str(triple.get("subject", "")).lower()
                obj = str(triple.get("object", "")).lower()
                if subj in query_entities:
                    graph_entity_names.add(obj)
                elif obj in query_entities:
                    graph_entity_names.add(subj)
        # Augment with graph neighbors
        graph_related = self._graph.get_related_entity_names_sync(
            query_entities,
            depth=2,
        )
        result = graph_entity_names | graph_related
        self._graph_cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # Entity index + query entity extraction
    # ------------------------------------------------------------------

    def build_entity_index(self, events: list[dict[str, Any]]) -> set[str]:
        """Collect all unique entity strings from events into a lowercase set."""
        index: set[str] = set()
        for evt in events:
            for e in evt.get("entities") or []:
                if isinstance(e, str) and e.strip():
                    index.add(e.strip().lower())
        return index

    def extract_query_entities(
        self,
        query: str,
        entity_index: set[str],
    ) -> set[str]:
        """Extract entities from a query by matching tokens against known entities.

        Complements the capitalization-based ``_extract_entities`` by handling
        lowercase queries like "who are alice and bob".  Matches unigrams and
        bigrams against the entity index built from events.
        """
        words = re.findall(r"[a-z0-9][\w-]*", query.lower())
        matched: set[str] = set()
        for w in words:
            if w in entity_index:
                matched.add(w)
        # Also check bigrams (e.g. "github actions", "knowledge graph")
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i + 1]}"
            if bigram in entity_index:
                matched.add(bigram)
        return matched

    # ------------------------------------------------------------------
    # Context line generation
    # ------------------------------------------------------------------

    def build_graph_context_lines(
        self,
        query: str,
        retrieved: list[dict[str, Any]],
        max_tokens: int = 100,
    ) -> list[str]:
        """Build entity relationship summary lines from graph and local event triples.

        Queries the knowledge graph first (when available), then falls back to
        scanning triples stored in local events.
        """
        query_entities: set[str] = set()
        if self._extractor is not None:
            query_entities = {e.lower() for e in self._extractor._extract_entities(query)}

        # Also extract entities via index lookup (handles lowercase queries).
        events = self._read_events_fn(limit=200)
        entity_index = self.build_entity_index(events)
        query_entities |= self.extract_query_entities(query, entity_index)

        for item in retrieved:
            for e in item.get("entities") or []:
                if isinstance(e, str) and e.strip():
                    query_entities.add(e.strip().lower())

        if not query_entities:
            return []

        # Collect relevant triples — graph first, then local event fallback.
        rel_triples: list[tuple[str, str, str]] = []

        if self._graph is not None and self._graph.enabled:
            rel_triples.extend(self._graph.get_triples_for_entities_sync(query_entities))

        # Supplement with local event triples (may add context the graph lacks).
        for evt in events:
            for triple in evt.get("triples") or []:
                subj = str(triple.get("subject", "")).strip()
                pred = str(triple.get("predicate", "")).strip()
                obj = str(triple.get("object", "")).strip()
                if not subj or not pred or not obj:
                    continue
                if subj.lower() in query_entities or obj.lower() in query_entities:
                    rel_triples.append((subj, pred, obj))

        if not rel_triples:
            return []

        # Deduplicate and format as compact lines, respecting token budget.
        # Annotate entities with ontology types to help the LLM disambiguate.
        from ..graph.entity_classifier import classify_entity_type

        seen: set[tuple[str, str, str]] = set()
        graph_lines: list[str] = []
        total_chars = 0
        max_chars = max_tokens * 4

        for subj, pred, obj in rel_triples:
            key = (subj.lower(), pred, obj.lower())
            if key in seen:
                continue
            seen.add(key)
            s_type = classify_entity_type(subj).value
            o_type = classify_entity_type(obj).value
            s_label = f"{subj} [{s_type}]" if s_type != "unknown" else subj
            o_label = f"{obj} [{o_type}]" if o_type != "unknown" else obj
            line = f"- {s_label} \u2192 {pred} \u2192 {o_label}"
            if total_chars + len(line) > max_chars:
                break
            graph_lines.append(line)
            total_chars += len(line)

        return graph_lines
