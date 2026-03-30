"""In-process knowledge graph backed by SQLite (GraphStore).

Architecture
------------
- **KnowledgeGraph** -- Primary public API.  Delegates all storage to
  ``GraphStore`` entity/edge tables.
- Write path: ``upsert_entity``, ``add_relationship``,
  ``ingest_event_triples`` (batch).
- Read path: ``get_neighbors``, ``find_paths``, ``query_subgraph``,
  ``get_entity``, ``search_entities``, ``resolve_entity``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from .entity_classifier import classify_entity_type, refine_type_from_predicate
from .ontology_rules import validate_triple_types
from .ontology_types import Entity, EntityType, Relationship, Triple

if TYPE_CHECKING:
    from ..db.graph_store import GraphStore


def _norm(name: str) -> str:
    """Canonical name normalisation: strip, lower, spaces to underscores."""
    return name.strip().lower().replace(" ", "_")


class KnowledgeGraph:
    """In-process knowledge graph backed by SQLite (GraphStore)."""

    def __init__(
        self,
        db: GraphStore | None = None,
    ) -> None:
        self._db = db
        self.enabled: bool = db is not None
        self.error: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def verify_connectivity(self) -> bool:
        """Return whether the graph is enabled."""
        return self.enabled

    async def close(self) -> None:
        """No-op -- db lifecycle managed by store.py."""

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    async def upsert_entity(self, entity: Entity) -> None:
        """Merge an entity node, updating properties and timestamps."""
        if not self.enabled or self._db is None:
            return
        canonical = entity.canonical_name
        aliases_text = ", ".join(entity.aliases)
        # Store display name in properties so it survives the canonical key
        merged_props = {**entity.properties, "_display_name": entity.name}
        props_json = json.dumps(merged_props)

        # Merge aliases with existing entity if present
        existing = self._db.get_entity(canonical)
        if existing:
            old_aliases = str(existing.get("aliases", ""))
            old_set = {a.strip() for a in old_aliases.split(",") if a.strip()}
            new_set = {a.strip() for a in aliases_text.split(",") if a.strip()}
            merged_aliases = sorted(old_set | new_set)
            aliases_text = ", ".join(merged_aliases)
            # Preserve first_seen from existing
            first_seen = existing.get("first_seen") or entity.first_seen
            # Merge properties (keep display name from new entity)
            old_props: dict[str, Any] = json.loads(existing.get("properties", "{}"))
            old_props.update(merged_props)
            props_json = json.dumps(old_props)
        else:
            first_seen = entity.first_seen

        self._db.upsert_entity(
            canonical,
            type=entity.entity_type.value,
            aliases=aliases_text,
            properties=props_json,
            first_seen=first_seen,
            last_seen=entity.last_seen,
        )

    async def add_relationship(self, rel: Relationship) -> None:
        """Merge a directed relationship edge between two entities."""
        if not self.enabled or self._db is None:
            return
        src = _norm(rel.source_id)
        tgt = _norm(rel.target_id)
        rel_type = rel.relation_type.value

        # Ensure source and target nodes exist (minimal stubs with display name)
        if self._db.get_entity(src) is None:
            self._db.upsert_entity(
                src, properties=json.dumps({"_display_name": rel.source_id.strip()})
            )
        if self._db.get_entity(tgt) is None:
            self._db.upsert_entity(
                tgt, properties=json.dumps({"_display_name": rel.target_id.strip()})
            )

        self._db.add_edge(
            src,
            tgt,
            relation=rel_type,
            confidence=rel.confidence,
            event_id=rel.source_event_id,
            timestamp=rel.timestamp,
        )

    async def ingest_event_triples(
        self,
        event_id: str,
        triples: list[Triple],
        *,
        timestamp: str = "",
    ) -> None:
        """Batch-upsert entities and relationships from extracted triples."""
        if not self.enabled or not triples:
            return
        for triple in triples:
            sub_type = classify_entity_type(triple.subject)
            obj_type = classify_entity_type(triple.object)
            sub_type = refine_type_from_predicate(
                sub_type,
                triple.predicate,
                is_subject=True,
            )
            obj_type = refine_type_from_predicate(
                obj_type,
                triple.predicate,
                is_subject=False,
            )

            # Validate domain/range constraints -- demote confidence on violation
            validation = validate_triple_types(triple.predicate, sub_type, obj_type)
            confidence = triple.confidence
            if not validation.valid:
                logger.debug(
                    "Triple constraint violation (%s): %s",
                    triple.predicate.value,
                    validation.reason,
                )
                confidence *= 0.5  # demote but still insert

            sub_entity = Entity(
                name=triple.subject,
                entity_type=sub_type,
                last_seen=timestamp,
                first_seen=timestamp,
            )
            obj_entity = Entity(
                name=triple.object,
                entity_type=obj_type,
                last_seen=timestamp,
                first_seen=timestamp,
            )

            rel = Relationship(
                source_id=triple.subject,
                target_id=triple.object,
                relation_type=triple.predicate,
                confidence=confidence,
                source_event_id=event_id,
                timestamp=timestamp,
            )

            await self.upsert_entity(sub_entity)
            await self.upsert_entity(obj_entity)
            await self.add_relationship(rel)

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    async def get_entity(self, name: str) -> Entity | None:
        """Look up an entity by canonical name or alias."""
        if not self.enabled or self._db is None:
            return None
        canonical = _norm(name)
        raw_lower = name.strip().lower()

        # Check by canonical name first
        row = self._db.get_entity(canonical)
        if row is not None:
            return self._row_to_entity(row)

        # Search aliases across all entities
        results = self._db.search_entities(raw_lower, limit=50)
        for r in results:
            aliases_text = str(r.get("aliases", "")).lower()
            if raw_lower in aliases_text:
                return self._row_to_entity(r)

        return None

    async def search_entities(
        self,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 10,
    ) -> list[Entity]:
        """Substring search across entity names and aliases."""
        if not self.enabled or self._db is None:
            return []
        query_lower = query.strip().lower()
        if not query_lower:
            return []

        results = self._db.search_entities(query_lower, limit=limit * 3)

        scored: list[tuple[float, Entity]] = []
        for row in results:
            if entity_type:
                etype_raw = str(row.get("type", "unknown"))
                if etype_raw != entity_type.value:
                    continue

            name = str(row.get("name", "")).lower()
            aliases_text = str(row.get("aliases", "")).lower()

            score = 0.0
            if query_lower == name:
                score = 1.0
            elif query_lower in name:
                score = 0.8
            elif query_lower in aliases_text:
                score = 0.6

            if score > 0:
                scored.append((score, self._row_to_entity(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entity for _, entity in scored[:limit]]

    async def get_neighbors(
        self,
        entity_name: str,
        depth: int = 1,
        relation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """BFS traversal returning edges up to *depth* hops."""
        if not self.enabled or self._db is None:
            return []
        canonical = _norm(entity_name)
        depth = max(1, min(depth, 5))

        if self._db.get_entity(canonical) is None:
            return []

        # Use DB BFS to find neighbor entities
        neighbors = self._db.get_neighbors(canonical, depth=depth)
        neighbor_names = {n["name"] for n in neighbors}
        all_names = neighbor_names | {canonical}

        # Collect edges touching any of the involved entities
        edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str, str]] = set()

        # Build display-name cache for all involved entities
        display: dict[str, str] = {}
        for n in all_names:
            display[n] = self._get_display_name(n)

        for name in all_names:
            for edge in self._db.get_edges_from(name):
                tgt = edge["target"]
                if tgt not in all_names:
                    continue
                rel = edge["relation"]
                if relation_types and rel not in relation_types:
                    continue
                key = (name, tgt, rel)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(
                        {
                            "source": display.get(name, name),
                            "relation": rel,
                            "target": display.get(tgt, tgt),
                            "confidence": edge.get("confidence", 0.0),
                        }
                    )

        return edges[:100]

    async def find_paths(
        self,
        source: str,
        target: str,
        max_depth: int = 3,
    ) -> list[list[dict[str, Any]]]:
        """Find paths between two entities.

        Uses iterative BFS. Returns up to 5 shortest paths.
        """
        if not self.enabled or self._db is None:
            return []
        src = _norm(source)
        tgt = _norm(target)
        max_depth = max(1, min(max_depth, 5))

        if self._db.get_entity(src) is None or self._db.get_entity(tgt) is None:
            return []

        # BFS for paths
        from collections import deque

        # Display-name cache
        _dn: dict[str, str] = {}

        def dn(canonical: str) -> str:
            if canonical not in _dn:
                _dn[canonical] = self._get_display_name(canonical)
            return _dn[canonical]

        def _edge_rel(n1: str, n2: str) -> str:
            """Find the relation between two adjacent canonical nodes."""
            assert self._db is not None
            for e in self._db.get_edges_from(n1):
                if e["target"] == n2:
                    return str(e["relation"])
            for e in self._db.get_edges_from(n2):
                if e["target"] == n1:
                    return str(e["relation"])
            return ""

        def _path_to_steps(node_path: list[str]) -> list[dict[str, Any]]:
            return [
                {
                    "source": dn(node_path[i]),
                    "relation": _edge_rel(node_path[i], node_path[i + 1]),
                    "target": dn(node_path[i + 1]),
                }
                for i in range(len(node_path) - 1)
            ]

        queue: deque[list[str]] = deque([[src]])
        paths: list[list[dict[str, Any]]] = []

        while queue and len(paths) < 5:
            path = queue.popleft()
            current = path[-1]
            if len(path) - 1 > max_depth:
                continue

            # Outgoing edges
            for edge in self._db.get_edges_from(current):
                neighbor = edge["target"]
                if neighbor in path:
                    continue
                new_path = path + [neighbor]
                if neighbor == tgt:
                    paths.append(_path_to_steps(new_path))
                elif len(new_path) - 1 < max_depth:
                    queue.append(new_path)

            # Incoming edges (undirected traversal)
            for edge in self._db.get_edges_to(current):
                neighbor = edge["source"]
                if neighbor in path:
                    continue
                new_path = path + [neighbor]
                if neighbor == tgt:
                    paths.append(_path_to_steps(new_path))
                elif len(new_path) - 1 < max_depth:
                    queue.append(new_path)

        return paths

    async def query_subgraph(
        self,
        entity_names: list[str],
        depth: int = 1,
    ) -> dict[str, Any]:
        """Return the merged subgraph around multiple entities."""
        if not self.enabled or not entity_names:
            return {"nodes": [], "edges": []}

        seen_edges: set[tuple[str, str, str]] = set()
        seen_nodes: set[str] = set()
        nodes: list[str] = []
        edges: list[dict[str, Any]] = []

        for name in entity_names:
            edge_list = await self.get_neighbors(name, depth=depth)
            for edge in edge_list:
                src = edge.get("source", "")
                tgt = edge.get("target", "")
                rel = edge.get("relation", "")
                key = (src, rel, tgt)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(edge)
                for n in (src, tgt):
                    if n and n not in seen_nodes:
                        seen_nodes.add(n)
                        nodes.append(n)

        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Sync methods (used by retrieval)
    # ------------------------------------------------------------------

    def get_related_entity_names_sync(
        self,
        entity_names: set[str],
        depth: int = 1,
    ) -> set[str]:
        """Synchronous neighbor lookup returning related entity names.

        Used by the sync ``retrieve()`` path in ``MemoryStore`` to collect
        graph-expanded entity names for scoring boosts.
        """
        if not self.enabled or not entity_names or self._db is None:
            return set()
        depth = max(1, min(depth, 3))
        related: set[str] = set()

        for name in entity_names:
            canonical = _norm(name)
            neighbors = self._db.get_neighbors(canonical, depth=depth)
            for n in neighbors:
                cn = str(n.get("name", ""))
                if cn:
                    related.add(cn)

        return related

    def get_triples_for_entities_sync(
        self,
        entity_names: set[str],
    ) -> list[tuple[str, str, str]]:
        """Synchronous triple lookup for building graph context lines.

        Returns ``(subject, predicate, object)`` tuples for relationships
        touching any of the given entity names.
        """
        if not self.enabled or not entity_names or self._db is None:
            return []
        triples: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()

        for name in entity_names:
            canonical = _norm(name)
            # Outgoing edges
            for edge in self._db.get_edges_from(canonical):
                src_display = self._get_display_name(canonical)
                rel = str(edge.get("relation", ""))
                tgt_display = self._get_display_name(str(edge.get("target", "")))
                if src_display and rel and tgt_display:
                    triple = (src_display, rel, tgt_display)
                    if triple not in seen:
                        seen.add(triple)
                        triples.append(triple)

            # Incoming edges
            for edge in self._db.get_edges_to(canonical):
                src_display = self._get_display_name(str(edge.get("source", "")))
                rel = str(edge.get("relation", ""))
                tgt_display = self._get_display_name(canonical)
                if src_display and rel and tgt_display:
                    triple = (src_display, rel, tgt_display)
                    if triple not in seen:
                        seen.add(triple)
                        triples.append(triple)

        return triples

    async def resolve_entity(self, name: str) -> str:
        """Return the canonical name for an entity (alias resolution).

        Falls back to the input name (lowered + underscored) if not found.
        """
        if not self.enabled:
            return _norm(name)
        entity = await self.get_entity(name)
        if entity:
            return entity.canonical_name
        return _norm(name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_entity(row: dict[str, Any]) -> Entity:
        """Convert a DB row dict to an ``Entity`` instance.

        Also handles the legacy networkx node-property format (``entity_type``,
        ``aliases_text``, ``prop_*`` keys) for backward compatibility.
        """
        # Support both DB format ("aliases") and legacy networkx format ("aliases_text")
        aliases_raw = str(row.get("aliases", "") or row.get("aliases_text", ""))
        aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]

        # Support both DB format ("type") and legacy networkx format ("entity_type")
        etype_raw = str(row.get("type", "") or row.get("entity_type", "unknown"))
        if not etype_raw:
            etype_raw = "unknown"
        try:
            etype = EntityType(etype_raw)
        except ValueError:
            etype = EntityType.UNKNOWN

        # Properties: DB format stores JSON string; legacy uses prop_* keys
        props_raw = row.get("properties")
        if isinstance(props_raw, str) and props_raw:
            try:
                props: dict[str, Any] = json.loads(props_raw)
            except (json.JSONDecodeError, TypeError):
                props = {}
        else:
            props = {}
        # Also collect legacy prop_* keys
        for k, v in row.items():
            if k.startswith("prop_"):
                props[k[5:]] = v

        # Use display name from properties if available (stored by upsert_entity),
        # falling back to the DB row name (canonical).
        display_name = props.pop("_display_name", None) or str(row.get("name", ""))

        return Entity(
            name=display_name,
            entity_type=etype,
            aliases=aliases,
            properties=props,
            first_seen=str(row.get("first_seen", "")),
            last_seen=str(row.get("last_seen", "")),
        )

    def _get_display_name(self, canonical: str) -> str:
        """Return the original display name for a canonical entity name."""
        if self._db is None:
            return canonical
        row = self._db.get_entity(canonical)
        if row is None:
            return canonical
        props_raw = row.get("properties", "{}")
        try:
            props = json.loads(props_raw) if props_raw else {}
        except (json.JSONDecodeError, TypeError):
            props = {}
        return str(props.get("_display_name", canonical))
