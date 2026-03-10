"""Neo4j-backed knowledge graph adapter for the memory subsystem.

Follows the same graceful-degradation pattern as ``_Mem0Adapter``:
if the ``neo4j`` package is not installed or the database is unreachable,
all public methods return empty results and ``enabled`` remains ``False``.

Architecture
------------
- **KnowledgeGraph** — Primary public API.  Wraps a Neo4j async Bolt
  driver with connection-pooling and health-check on init.
- Write path: ``upsert_entity``, ``add_relationship``,
  ``ingest_event_triples`` (batch).
- Read path: ``get_neighbors``, ``find_paths``, ``query_subgraph``,
  ``get_entity``, ``search_entities``, ``resolve_entity``.
- Schema: ``ensure_indexes`` creates uniqueness constraints and a
  full-text index on entity names/aliases.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .ontology import (
    Entity,
    EntityType,
    Relationship,
    Triple,
    classify_entity_type,
    refine_type_from_predicate,
)

try:
    from neo4j import (  # type: ignore[import-untyped]
        AsyncDriver,
        AsyncGraphDatabase,
        GraphDatabase,
    )

    _HAS_NEO4J = True
except Exception:  # pragma: no cover – optional dependency
    AsyncGraphDatabase = None  # type: ignore[assignment,misc]
    AsyncDriver = None  # type: ignore[assignment,misc]
    GraphDatabase = None  # type: ignore[assignment,misc]
    _HAS_NEO4J = False

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """Neo4j-backed knowledge graph with graceful degradation.

    Parameters
    ----------
    uri:
        Bolt URI (e.g. ``bolt://localhost:7687``).
    auth:
        ``"user/password"`` string split on ``/``.
    database:
        Neo4j database name (default ``"neo4j"``).
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        auth: str = "neo4j/nanobot_graph",
        database: str = "neo4j",
    ) -> None:
        self._uri = uri
        self._database = database
        self._driver: Any | None = None
        self._sync_driver: Any | None = None
        self.enabled: bool = False
        self.error: str | None = None

        if not _HAS_NEO4J:
            self.error = "neo4j package not installed"
            return

        parts = auth.split("/", 1)
        user = parts[0]
        password = parts[1] if len(parts) > 1 else ""

        try:
            self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
            self._sync_driver = GraphDatabase.driver(uri, auth=(user, password))
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            self.error = f"Neo4j driver init failed: {exc}"
            logger.warning("KnowledgeGraph disabled: %s", self.error)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def verify_connectivity(self) -> bool:
        """Attempt a lightweight connectivity check.  Returns ``True`` on
        success, sets ``enabled = False`` on failure."""
        if not self._driver:
            return False
        try:
            await self._driver.verify_connectivity()
            self.enabled = True
            return True
        except Exception as exc:  # noqa: BLE001
            self.enabled = False
            self.error = f"connectivity check failed: {exc}"
            logger.warning("KnowledgeGraph disabled: %s", self.error)
            return False

    async def close(self) -> None:
        """Close the underlying drivers."""
        if self._driver:
            await self._driver.close()
            self._driver = None
        if self._sync_driver:
            self._sync_driver.close()
            self._sync_driver = None
            self.enabled = False

    # ------------------------------------------------------------------
    # Schema setup
    # ------------------------------------------------------------------

    async def ensure_indexes(self) -> None:
        """Create uniqueness constraints and full-text indexes (idempotent)."""
        if not self.enabled or self._driver is None:
            return
        queries = [
            (
                "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.canonical_name IS UNIQUE"
            ),
            (
                "CREATE FULLTEXT INDEX entity_search IF NOT EXISTS "
                "FOR (e:Entity) ON EACH [e.name, e.aliases_text]"
            ),
        ]
        try:
            async with self._driver.session(database=self._database) as session:
                for q in queries:
                    await session.run(q)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_indexes failed: %s", exc)

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    async def upsert_entity(self, entity: Entity) -> None:
        """MERGE an entity node, updating properties and timestamps."""
        if not self.enabled or self._driver is None:
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

        cypher = (
            "MERGE (e:Entity {canonical_name: $canonical_name}) "
            "ON CREATE SET e = $props "
            "ON MATCH SET e += $props"
        )
        try:
            async with self._driver.session(database=self._database) as session:
                await session.run(cypher, canonical_name=canonical, props=props)
        except Exception as exc:  # noqa: BLE001
            logger.warning("upsert_entity failed for %s: %s", entity.name, exc)

    async def add_relationship(self, rel: Relationship) -> None:
        """MERGE a directed relationship edge between two entities."""
        if not self.enabled or self._driver is None:
            return
        src = rel.source_id.strip().lower().replace(" ", "_")
        tgt = rel.target_id.strip().lower().replace(" ", "_")
        rel_type = rel.relation_type.value  # e.g. "WORKS_ON"

        # Dynamic relationship type via APOC-free pattern: use generic REL
        # edge with a `type` property, since parameterised rel types are not
        # supported in Cypher MERGE.  Trade-off: simpler setup, filterable
        # via property.
        cypher = (
            "MERGE (s:Entity {canonical_name: $src}) "
            "MERGE (t:Entity {canonical_name: $tgt}) "
            "MERGE (s)-[r:REL {type: $rel_type}]->(t) "
            "ON CREATE SET r.confidence = $confidence, "
            "  r.source_event_id = $event_id, r.timestamp = $ts "
            "ON MATCH SET r.confidence = CASE WHEN $confidence > r.confidence "
            "  THEN $confidence ELSE r.confidence END, "
            "  r.timestamp = $ts"
        )
        params = {
            "src": src,
            "tgt": tgt,
            "rel_type": rel_type,
            "confidence": rel.confidence,
            "event_id": rel.source_event_id,
            "ts": rel.timestamp,
        }
        try:
            async with self._driver.session(database=self._database) as session:
                await session.run(cypher, **params)
        except Exception as exc:  # noqa: BLE001
            logger.warning("add_relationship failed %s->%s: %s", src, tgt, exc)

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
                sub_type, triple.predicate, is_subject=True,
            )
            obj_type = refine_type_from_predicate(
                obj_type, triple.predicate, is_subject=False,
            )

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
                confidence=triple.confidence,
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
        if not self.enabled or self._driver is None:
            return None
        canonical = name.strip().lower().replace(" ", "_")
        cypher = (
            "MATCH (e:Entity) "
            "WHERE e.canonical_name = $name OR e.aliases_text CONTAINS $raw "
            "RETURN e LIMIT 1"
        )
        try:
            async with self._driver.session(database=self._database) as session:
                result = await session.run(cypher, name=canonical, raw=name.strip().lower())
                record = await result.single()
                if not record:
                    return None
                node = record["e"]
                return self._node_to_entity(dict(node))
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_entity failed for %s: %s", name, exc)
            return None

    async def search_entities(
        self,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 10,
    ) -> list[Entity]:
        """Fuzzy text search across entity names and aliases."""
        if not self.enabled or self._driver is None:
            return []
        # Use full-text index for fuzzy matching
        cypher = (
            "CALL db.index.fulltext.queryNodes('entity_search', $query) "
            "YIELD node, score "
        )
        if entity_type:
            cypher += "WHERE node.entity_type = $etype "
        cypher += "RETURN node ORDER BY score DESC LIMIT $limit"

        params: dict[str, Any] = {"query": query, "limit": limit}
        if entity_type:
            params["etype"] = entity_type.value

        try:
            async with self._driver.session(database=self._database) as session:
                result = await session.run(cypher, **params)
                records = await result.data()
                return [self._node_to_entity(dict(r["node"])) for r in records]
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_entities failed: %s", exc)
            return []

    async def get_neighbors(
        self,
        entity_name: str,
        depth: int = 1,
        relation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """BFS traversal returning nodes + edges up to *depth* hops."""
        if not self.enabled or self._driver is None:
            return []
        canonical = entity_name.strip().lower().replace(" ", "_")
        depth = max(1, min(depth, 5))  # clamp to [1, 5]

        cypher = (
            f"MATCH path = (start:Entity {{canonical_name: $name}})"
            f"-[r:REL*1..{depth}]-(neighbor:Entity) "
        )
        if relation_types:
            type_list = ", ".join(f"'{t}'" for t in relation_types)
            cypher += f"WHERE ALL(rel IN r WHERE rel.type IN [{type_list}]) "
        cypher += (
            "UNWIND relationships(path) AS edge "
            "WITH DISTINCT startNode(edge) AS src, edge, endNode(edge) AS tgt "
            "RETURN src.name AS source, edge.type AS relation, "
            "tgt.name AS target, edge.confidence AS confidence "
            "LIMIT 100"
        )
        try:
            async with self._driver.session(database=self._database) as session:
                result = await session.run(cypher, name=canonical)
                data: list[dict[str, Any]] = await result.data()
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_neighbors failed for %s: %s", entity_name, exc)
            return []

    async def find_paths(
        self,
        source: str,
        target: str,
        max_depth: int = 3,
    ) -> list[list[dict[str, Any]]]:
        """Find shortest paths between two entities."""
        if not self.enabled or self._driver is None:
            return []
        src = source.strip().lower().replace(" ", "_")
        tgt = target.strip().lower().replace(" ", "_")
        max_depth = max(1, min(max_depth, 5))

        cypher = (
            "MATCH path = shortestPath("
            "(s:Entity {canonical_name: $src})-[r:REL*1.." + str(max_depth) + "]-"
            "(t:Entity {canonical_name: $tgt})) "
            "RETURN [n IN nodes(path) | n.name] AS nodes, "
            "[r IN relationships(path) | r.type] AS relations "
            "LIMIT 5"
        )
        try:
            async with self._driver.session(database=self._database) as session:
                result = await session.run(cypher, src=src, tgt=tgt)
                records = await result.data()
                paths: list[list[dict[str, Any]]] = []
                for rec in records:
                    path_steps: list[dict[str, Any]] = []
                    nodes = rec["nodes"]
                    relations = rec["relations"]
                    for i, rel in enumerate(relations):
                        path_steps.append({
                            "source": nodes[i],
                            "relation": rel,
                            "target": nodes[i + 1],
                        })
                    paths.append(path_steps)
                return paths
        except Exception as exc:  # noqa: BLE001
            logger.warning("find_paths failed %s->%s: %s", source, target, exc)
            return []

    async def query_subgraph(
        self,
        entity_names: list[str],
        depth: int = 1,
    ) -> dict[str, Any]:
        """Return the merged subgraph around multiple entities."""
        if not self.enabled or not entity_names:
            return {"nodes": [], "edges": []}

        tasks = [self.get_neighbors(name, depth=depth) for name in entity_names]
        all_edges = await asyncio.gather(*tasks)

        seen_edges: set[tuple[str, str, str]] = set()
        seen_nodes: set[str] = set()
        nodes: list[str] = []
        edges: list[dict[str, Any]] = []

        for edge_list in all_edges:
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

    def get_related_entity_names_sync(
        self,
        entity_names: set[str],
        depth: int = 1,
    ) -> set[str]:
        """Synchronous neighbor lookup returning related entity names.

        Used by the sync ``retrieve()`` path in ``MemoryStore`` to collect
        graph-expanded entity names for scoring boosts.  Returns an empty
        set when the graph is disabled or the sync driver is unavailable.
        """
        if not self.enabled or not self._sync_driver or not entity_names:
            return set()
        depth = max(1, min(depth, 3))
        related: set[str] = set()
        try:
            with self._sync_driver.session(database=self._database) as session:
                for name in entity_names:
                    canonical = name.strip().lower().replace(" ", "_")
                    # Try exact match first, then fall back to CONTAINS.
                    cypher = (
                        f"MATCH (start:Entity)"
                        f"-[r:REL*1..{depth}]-(neighbor:Entity) "
                        "WHERE start.canonical_name = $name "
                        "   OR start.canonical_name CONTAINS $name "
                        "RETURN DISTINCT neighbor.canonical_name AS cn, "
                        "neighbor.name AS n LIMIT 50"
                    )
                    result = session.run(cypher, name=canonical)
                    for record in result:
                        cn = record.get("cn", "")
                        n = record.get("n", "")
                        if cn:
                            related.add(cn)
                        if n:
                            related.add(n.lower())
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_related_entity_names_sync failed: %s", exc)
        return related

    def get_triples_for_entities_sync(
        self,
        entity_names: set[str],
    ) -> list[tuple[str, str, str]]:
        """Synchronous triple lookup for building graph context lines.

        Returns ``(subject, predicate, object)`` tuples for relationships
        touching any of the given entity names.
        """
        if not self.enabled or not self._sync_driver or not entity_names:
            return []
        triples: list[tuple[str, str, str]] = []
        try:
            with self._sync_driver.session(database=self._database) as session:
                for name in entity_names:
                    canonical = name.strip().lower().replace(" ", "_")
                    cypher = (
                        "MATCH (s:Entity)-[r:REL]-(t:Entity) "
                        "WHERE s.canonical_name = $name "
                        "   OR s.canonical_name CONTAINS $name "
                        "RETURN s.name AS source, r.type AS relation, "
                        "t.name AS target LIMIT 30"
                    )
                    result = session.run(cypher, name=canonical)
                    for record in result:
                        src = record.get("source", "")
                        rel = record.get("relation", "")
                        tgt = record.get("target", "")
                        if src and rel and tgt:
                            triples.append((src, rel, tgt))
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_triples_for_entities_sync failed: %s", exc)
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
        """Convert a Neo4j node-property dict to an ``Entity`` instance."""
        # Extract custom properties (stored as prop_*)
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
