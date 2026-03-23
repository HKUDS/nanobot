"""In-process knowledge graph backed by networkx DiGraph + JSON persistence.

Architecture
------------
- **KnowledgeGraph** — Primary public API.  Uses a ``networkx.DiGraph``
  for in-memory graph operations and persists to a JSON file alongside
  other memory artefacts.
- Write path: ``upsert_entity``, ``add_relationship``,
  ``ingest_event_triples`` (batch).
- Read path: ``get_neighbors``, ``find_paths``, ``query_subgraph``,
  ``get_entity``, ``search_entities``, ``resolve_entity``.
- Schema: ``ensure_indexes`` is a no-op (kept for interface compat).
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

import networkx as nx
from loguru import logger

from .entity_classifier import classify_entity_type, refine_type_from_predicate
from .ontology_rules import validate_triple_types
from .ontology_types import Entity, EntityType, Relationship, Triple


class KnowledgeGraph:
    """In-process knowledge graph backed by networkx DiGraph + JSON persistence."""

    def __init__(self, workspace: Path | None = None) -> None:
        self._graph = nx.DiGraph()
        self._workspace = workspace
        self._json_path = (workspace / "memory" / "knowledge_graph.json") if workspace else None
        self.enabled: bool = workspace is not None
        self.error: str | None = None
        if self.enabled and self._json_path and self._json_path.exists():
            self._load()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def verify_connectivity(self) -> bool:
        """Return whether the graph is enabled."""
        return self.enabled

    async def close(self) -> None:
        """Persist graph to disk and release resources."""
        if self.enabled:
            self._save()

    async def ensure_indexes(self) -> None:
        """No-op — networkx does not require index setup."""

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    async def upsert_entity(self, entity: Entity) -> None:
        """Merge an entity node, updating properties and timestamps."""
        if not self.enabled:
            return
        canonical = entity.canonical_name
        props: dict[str, Any] = {
            "name": entity.name,
            "canonical_name": canonical,
            "entity_type": entity.entity_type.value,
            "aliases_text": ", ".join(entity.aliases),
            "first_seen": entity.first_seen,
            "last_seen": entity.last_seen,
        }
        props.update({f"prop_{k}": v for k, v in entity.properties.items()})

        if canonical in self._graph:
            existing = dict(self._graph.nodes[canonical])
            # Merge aliases
            old_aliases = str(existing.get("aliases_text", ""))
            old_set = {a.strip() for a in old_aliases.split(",") if a.strip()}
            new_set = {a.strip() for a in props["aliases_text"].split(",") if a.strip()}
            merged_aliases = sorted(old_set | new_set)
            props["aliases_text"] = ", ".join(merged_aliases)
            # Preserve first_seen from existing
            if existing.get("first_seen"):
                props["first_seen"] = existing["first_seen"]
            existing.update(props)
            self._graph.nodes[canonical].update(existing)
        else:
            self._graph.add_node(canonical, **props)

        self._save()

    async def add_relationship(self, rel: Relationship) -> None:
        """Merge a directed relationship edge between two entities."""
        if not self.enabled:
            return
        src = rel.source_id.strip().lower().replace(" ", "_")
        tgt = rel.target_id.strip().lower().replace(" ", "_")
        rel_type = rel.relation_type.value

        # Ensure source and target nodes exist (minimal stubs with display name)
        if src not in self._graph:
            self._graph.add_node(src, canonical_name=src, name=rel.source_id.strip())
        if tgt not in self._graph:
            self._graph.add_node(tgt, canonical_name=tgt, name=rel.target_id.strip())

        self._merge_edge(src, tgt, rel_type, rel.confidence, rel.source_event_id, rel.timestamp)
        self._save()

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

            # Validate domain/range constraints — demote confidence on violation
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
        if not self.enabled:
            return None
        canonical = name.strip().lower().replace(" ", "_")
        raw = name.strip().lower()

        # Check by canonical_name first
        if canonical in self._graph:
            return self._node_to_entity(dict(self._graph.nodes[canonical]))

        # Check aliases across all nodes
        for _node_id, data in self._graph.nodes(data=True):
            aliases_text = str(data.get("aliases_text", ""))
            if raw in aliases_text.lower():
                return self._node_to_entity(dict(data))

        return None

    async def search_entities(
        self,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 10,
    ) -> list[Entity]:
        """Substring search across entity names and aliases."""
        if not self.enabled:
            return []
        query_lower = query.strip().lower()
        scored: list[tuple[float, Entity]] = []

        for _node_id, data in self._graph.nodes(data=True):
            if entity_type:
                etype_raw = str(data.get("entity_type", "unknown"))
                if etype_raw != entity_type.value:
                    continue

            name = str(data.get("name", "")).lower()
            canonical = str(data.get("canonical_name", "")).lower()
            aliases_text = str(data.get("aliases_text", "")).lower()

            score = 0.0
            if query_lower == canonical or query_lower == name:
                score = 1.0
            elif query_lower in name:
                score = 0.8
            elif query_lower in canonical:
                score = 0.7
            elif query_lower in aliases_text:
                score = 0.6

            if score > 0:
                scored.append((score, self._node_to_entity(dict(data))))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entity for _, entity in scored[:limit]]

    async def get_neighbors(
        self,
        entity_name: str,
        depth: int = 1,
        relation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """BFS traversal returning edges up to *depth* hops."""
        if not self.enabled:
            return []
        canonical = entity_name.strip().lower().replace(" ", "_")
        depth = max(1, min(depth, 5))

        if canonical not in self._graph:
            return []

        # BFS collecting edges (undirected traversal)
        visited: set[str] = {canonical}
        queue: deque[tuple[str, int]] = deque([(canonical, 0)])
        edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str, str]] = set()

        while queue:
            current, d = queue.popleft()
            if d >= depth:
                continue

            # Outgoing edges
            for _, tgt, edata in self._graph.out_edges(current, data=True):
                rel_type = edata.get("type", "")
                if relation_types and rel_type not in relation_types:
                    continue
                edge_key = (current, tgt, rel_type)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    src_name = self._get_node_name(current)
                    tgt_name = self._get_node_name(tgt)
                    edges.append(
                        {
                            "source": src_name,
                            "relation": rel_type,
                            "target": tgt_name,
                            "confidence": edata.get("confidence", 0.0),
                        }
                    )
                if tgt not in visited:
                    visited.add(tgt)
                    queue.append((tgt, d + 1))

            # Incoming edges (undirected traversal like Neo4j's -[]-)
            for src, _, edata in self._graph.in_edges(current, data=True):
                rel_type = edata.get("type", "")
                if relation_types and rel_type not in relation_types:
                    continue
                edge_key = (src, current, rel_type)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    src_name = self._get_node_name(src)
                    tgt_name = self._get_node_name(current)
                    edges.append(
                        {
                            "source": src_name,
                            "relation": rel_type,
                            "target": tgt_name,
                            "confidence": edata.get("confidence", 0.0),
                        }
                    )
                if src not in visited:
                    visited.add(src)
                    queue.append((src, d + 1))

        return edges[:100]

    async def find_paths(
        self,
        source: str,
        target: str,
        max_depth: int = 3,
    ) -> list[list[dict[str, Any]]]:
        """Find paths between two entities."""
        if not self.enabled:
            return []
        src = source.strip().lower().replace(" ", "_")
        tgt = target.strip().lower().replace(" ", "_")
        max_depth = max(1, min(max_depth, 5))

        if src not in self._graph or tgt not in self._graph:
            return []

        # Use undirected view for path finding (matches Neo4j's undirected pattern)
        undirected = self._graph.to_undirected()
        paths: list[list[dict[str, Any]]] = []
        try:
            for path_nodes in nx.all_simple_paths(undirected, src, tgt, cutoff=max_depth):
                path_steps: list[dict[str, Any]] = []
                for i in range(len(path_nodes) - 1):
                    n1, n2 = path_nodes[i], path_nodes[i + 1]
                    # Check both directions for the edge
                    edata = self._graph.get_edge_data(n1, n2)
                    if edata is None:
                        edata = self._graph.get_edge_data(n2, n1)
                    rel_type = edata.get("type", "") if edata else ""
                    path_steps.append(
                        {
                            "source": self._get_node_name(n1),
                            "relation": rel_type,
                            "target": self._get_node_name(n2),
                        }
                    )
                paths.append(path_steps)
                if len(paths) >= 5:
                    break
        except nx.NetworkXError:  # crash-barrier: no path exists between entities
            pass

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
        if not self.enabled or not entity_names:
            return set()
        depth = max(1, min(depth, 3))
        related: set[str] = set()

        for name in entity_names:
            canonical = name.strip().lower().replace(" ", "_")
            # Collect nodes matching by canonical_name or containing the name
            start_nodes: list[str] = []
            for node_id, data in self._graph.nodes(data=True):
                cn = str(data.get("canonical_name", node_id))
                if cn == canonical or canonical in cn:
                    start_nodes.append(node_id)

            for start in start_nodes:
                # BFS up to depth
                visited: set[str] = {start}
                queue: deque[tuple[str, int]] = deque([(start, 0)])
                while queue:
                    current, d = queue.popleft()
                    if d >= depth:
                        continue
                    for neighbor in set(self._graph.successors(current)) | set(
                        self._graph.predecessors(current)
                    ):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            ndata = self._graph.nodes[neighbor]
                            cn = str(ndata.get("canonical_name", neighbor))
                            n = str(ndata.get("name", ""))
                            if cn:
                                related.add(cn)
                            if n:
                                related.add(n.lower())
                            queue.append((neighbor, d + 1))

        return related

    def get_triples_for_entities_sync(
        self,
        entity_names: set[str],
    ) -> list[tuple[str, str, str]]:
        """Synchronous triple lookup for building graph context lines.

        Returns ``(subject, predicate, object)`` tuples for relationships
        touching any of the given entity names.
        """
        if not self.enabled or not entity_names:
            return []
        triples: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()

        for name in entity_names:
            canonical = name.strip().lower().replace(" ", "_")
            # Find matching nodes
            matching_nodes: list[str] = []
            for node_id, data in self._graph.nodes(data=True):
                cn = str(data.get("canonical_name", node_id))
                if cn == canonical or canonical in cn:
                    matching_nodes.append(node_id)

            for node in matching_nodes:
                # Outgoing
                for _, tgt, edata in self._graph.out_edges(node, data=True):
                    src_name = self._get_node_name(node)
                    rel = str(edata.get("type", ""))
                    tgt_name = self._get_node_name(tgt)
                    if src_name and rel and tgt_name:
                        triple = (src_name, rel, tgt_name)
                        if triple not in seen:
                            seen.add(triple)
                            triples.append(triple)

                # Incoming
                for src, _, edata in self._graph.in_edges(node, data=True):
                    src_name = self._get_node_name(src)
                    rel = str(edata.get("type", ""))
                    tgt_name = self._get_node_name(node)
                    if src_name and rel and tgt_name:
                        triple = (src_name, rel, tgt_name)
                        if triple not in seen:
                            seen.add(triple)
                            triples.append(triple)

        return triples

    async def resolve_entity(self, name: str) -> str:
        """Return the canonical name for an entity (alias resolution).

        Falls back to the input name (lowered + underscored) if not found.
        """
        if not self.enabled:
            return name.strip().lower().replace(" ", "_")
        entity = await self.get_entity(name)
        if entity:
            return entity.canonical_name
        return name.strip().lower().replace(" ", "_")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _node_to_entity(props: dict[str, Any]) -> Entity:
        """Convert a node-property dict to an ``Entity`` instance."""
        extra: dict[str, Any] = {}
        for k, v in props.items():
            if k.startswith("prop_"):
                extra[k[5:]] = v

        aliases_raw = str(props.get("aliases_text", ""))
        aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]

        etype_raw = str(props.get("entity_type", "unknown"))
        try:
            etype = EntityType(etype_raw)
        except ValueError:
            etype = EntityType.UNKNOWN

        return Entity(
            name=str(props.get("name", "")),
            entity_type=etype,
            aliases=aliases,
            properties=extra,
            first_seen=str(props.get("first_seen", "")),
            last_seen=str(props.get("last_seen", "")),
        )

    def _get_node_name(self, node_id: str) -> str:
        """Return the display name for a node, falling back to node_id."""
        if node_id in self._graph:
            return str(self._graph.nodes[node_id].get("name", node_id))
        return node_id

    def _merge_edge(
        self,
        src: str,
        tgt: str,
        rel_type: str,
        confidence: float,
        source_event_id: str,
        timestamp: str,
    ) -> None:
        """Merge an edge into the graph, updating confidence if higher."""
        existing_edge = self._graph.get_edge_data(src, tgt)
        if existing_edge and existing_edge.get("type") == rel_type:
            old_conf = existing_edge.get("confidence", 0.0)
            self._graph[src][tgt]["confidence"] = max(old_conf, confidence)
            self._graph[src][tgt]["timestamp"] = timestamp
        else:
            self._graph.add_edge(
                src,
                tgt,
                type=rel_type,
                confidence=confidence,
                source_event_id=source_event_id,
                timestamp=timestamp,
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read JSON file and rebuild the DiGraph."""
        if not self._json_path:
            return
        try:
            raw = self._json_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            self._graph.clear()
            for node in data.get("nodes", []):
                node_id = node.pop("id", node.get("canonical_name", ""))
                self._graph.add_node(node_id, **node)
            for edge in data.get("edges", []):
                src = edge.pop("source", "")
                tgt = edge.pop("target", "")
                if src and tgt:
                    self._graph.add_edge(src, tgt, **edge)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KnowledgeGraph._load failed: {}", exc)

    def _save(self) -> None:
        """Serialize DiGraph to JSON."""
        if not self._json_path:
            return
        try:
            nodes: list[dict[str, Any]] = []
            for node_id, data in self._graph.nodes(data=True):
                entry = {"id": node_id}
                entry.update(data)
                nodes.append(entry)

            edges: list[dict[str, Any]] = []
            for src, tgt, data in self._graph.edges(data=True):
                entry = {"source": src, "target": tgt}
                entry.update(data)
                edges.append(entry)

            payload = {"nodes": nodes, "edges": edges}

            # Atomic write: write to temp file then rename
            self._json_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._json_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self._json_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KnowledgeGraph._save failed: {}", exc)
