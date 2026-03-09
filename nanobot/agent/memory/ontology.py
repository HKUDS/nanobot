"""Entity ontology and relationship types for the knowledge graph.

Defines typed entities, relationships, and triples that form the
foundation of Nanobot's knowledge graph layer.  Entity type
classification uses a combination of keyword heuristics and explicit
type annotations.

Architecture
------------
- **EntityType** — Rich enum hierarchy covering people, systems,
  concepts, locations, projects, and organisations.
- **RelationType** — Fixed predicate vocabulary for relationship edges.
- **Entity / Relationship / Triple** — Lightweight dataclasses for
  graph nodes, edges, and raw extraction output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Entity types — rich ontology with subtypes
# ---------------------------------------------------------------------------

class EntityType(str, Enum):
    """Typed entity categories with subtypes."""

    # People
    PERSON = "person"

    # Systems (subtypes)
    SYSTEM = "system"
    SERVICE = "service"
    DATABASE = "database"
    API = "api"

    # Concepts (subtypes)
    CONCEPT = "concept"
    TECHNOLOGY = "technology"
    FRAMEWORK = "framework"
    PATTERN = "pattern"

    # Locations (subtypes)
    LOCATION = "location"
    REGION = "region"
    ENVIRONMENT = "environment"

    # Organisational
    PROJECT = "project"
    ORGANIZATION = "organization"

    # Fallback
    UNKNOWN = "unknown"

    @classmethod
    def parent_type(cls, entity_type: EntityType) -> EntityType:
        """Return the parent category for a subtype."""
        _parents: dict[EntityType, EntityType] = {
            cls.SERVICE: cls.SYSTEM,
            cls.DATABASE: cls.SYSTEM,
            cls.API: cls.SYSTEM,
            cls.TECHNOLOGY: cls.CONCEPT,
            cls.FRAMEWORK: cls.CONCEPT,
            cls.PATTERN: cls.CONCEPT,
            cls.REGION: cls.LOCATION,
            cls.ENVIRONMENT: cls.LOCATION,
        }
        return _parents.get(entity_type, entity_type)


# ---------------------------------------------------------------------------
# Relationship types
# ---------------------------------------------------------------------------

class RelationType(str, Enum):
    """Fixed predicate vocabulary for knowledge-graph edges."""

    WORKS_ON = "WORKS_ON"
    WORKS_WITH = "WORKS_WITH"
    USES = "USES"
    LOCATED_IN = "LOCATED_IN"
    CAUSED_BY = "CAUSED_BY"
    RELATED_TO = "RELATED_TO"
    OWNS = "OWNS"
    DEPENDS_ON = "DEPENDS_ON"
    SUPERSEDES = "SUPERSEDES"
    MENTIONS = "MENTIONS"
    CONSTRAINED_BY = "CONSTRAINED_BY"

    @classmethod
    def from_str(cls, value: str) -> RelationType:
        """Parse a relation string, falling back to RELATED_TO."""
        normalized = value.strip().upper().replace(" ", "_")
        try:
            return cls(normalized)
        except ValueError:
            return cls.RELATED_TO


# ---------------------------------------------------------------------------
# Graph data classes
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Entity:
    """A typed node in the knowledge graph."""

    name: str
    entity_type: EntityType = EntityType.UNKNOWN
    aliases: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""

    @property
    def canonical_name(self) -> str:
        """Normalised lowercase name used as the graph key."""
        return self.name.strip().lower().replace(" ", "_")


@dataclass(slots=True)
class Relationship:
    """A typed directed edge between two entities."""

    source_id: str
    target_id: str
    relation_type: RelationType
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.7
    source_event_id: str = ""
    timestamp: str = ""


@dataclass(slots=True)
class Triple:
    """A raw subject-predicate-object extraction from an event."""

    subject: str
    predicate: RelationType
    object: str
    confidence: float = 0.7
    source_event_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict matching the event schema extension."""
        return {
            "subject": self.subject,
            "predicate": self.predicate.value,
            "object": self.object,
            "confidence": self.confidence,
            "source_event_id": self.source_event_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source_event_id: str = "") -> Triple:
        """Deserialise from a dict (e.g. from events.jsonl)."""
        return cls(
            subject=str(data.get("subject", "")).strip(),
            predicate=RelationType.from_str(str(data.get("predicate", "RELATED_TO"))),
            object=str(data.get("object", "")).strip(),
            confidence=min(max(float(data.get("confidence", 0.7)), 0.0), 1.0),
            source_event_id=source_event_id or str(data.get("source_event_id", "")),
        )


# ---------------------------------------------------------------------------
# Entity type classification heuristic
# ---------------------------------------------------------------------------

# Keyword maps for heuristic entity type inference.  Keys are lowercased
# substrings checked against the entity name; the first match wins.
_TYPE_KEYWORDS: list[tuple[EntityType, tuple[str, ...]]] = [
    # People — common name indicators
    (EntityType.PERSON, ("carlos", "alice", "bob", "user", "manager", "lead", "engineer")),
    # Regions / locations
    (EntityType.REGION, (
        "eu-west", "us-east", "ap-south", "us-west", "eu-central",
        "region", "zone", "datacenter",
    )),
    (EntityType.ENVIRONMENT, ("prod", "staging", "development", "local", "ci/cd", "ci")),
    # Databases
    (EntityType.DATABASE, ("postgres", "mysql", "redis", "mongo", "sqlite", "qdrant", "neo4j")),
    # APIs
    (EntityType.API, ("api", "endpoint", "graphql", "rest", "grpc", "webhook")),
    # Services
    (EntityType.SERVICE, ("gateway", "proxy", "broker", "queue", "worker", "scheduler")),
    # Frameworks / technologies
    (EntityType.FRAMEWORK, ("django", "flask", "fastapi", "react", "vue", "next", "pydantic")),
    (EntityType.TECHNOLOGY, (
        "python", "javascript", "typescript", "docker", "kubernetes",
        "oauth", "oauth2", "terraform", "ansible",
    )),
    # Patterns
    (EntityType.PATTERN, ("pattern", "strategy", "singleton", "observer", "decorator")),
    # Projects
    (EntityType.PROJECT, ("project", "sprint", "epic", "milestone", "roadmap", "rollout")),
    # Organisations
    (EntityType.ORGANIZATION, ("team", "org", "company", "department", "platform team")),
]


def classify_entity_type(name: str) -> EntityType:
    """Infer an entity type from its name using keyword heuristics.

    Returns ``EntityType.UNKNOWN`` when no pattern matches.
    """
    lowered = name.strip().lower()
    if not lowered:
        return EntityType.UNKNOWN
    for entity_type, keywords in _TYPE_KEYWORDS:
        for keyword in keywords:
            if keyword in lowered:
                return entity_type
    return EntityType.UNKNOWN
