"""Schema types for the knowledge graph ontology.

Defines the typed vocabulary (entity types, relation types) and the
lightweight dataclasses that form graph nodes, edges, and extraction
output.  This module is the **source of truth** for the graph schema —
classifiers, linkers, and rules import from here.

Design decisions
----------------
- ``EntityType`` covers both **software-infra** and **agent-native**
  concepts (agent, task, action, observation, etc.).
- ``Entity.secondary_types`` allows multi-label typing so the graph
  can represent that *Neo4j* is a DATABASE **and** a TECHNOLOGY.
- ``Entity.properties`` may carry external grounding keys such as
  ``wikidata_id`` or ``external_uri``.
- ``RelationType`` includes operational predicates needed for agent
  cognition graphs (PERFORMS, PRODUCES, RECALLS, …).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Entity types — rich ontology with software-infra + agent-native subtypes
# ---------------------------------------------------------------------------


class EntityType(str, Enum):
    """Typed entity categories with subtypes.

    The hierarchy is split into five groups:

    1. **People** — human participants.
    2. **Systems** — software infrastructure (services, databases, APIs).
    3. **Concepts** — abstract knowledge (technologies, patterns).
    4. **Locations** — physical or logical places (regions, environments).
    5. **Organisational** — teams, projects.
    6. **Agent-native** — types specific to agent cognition and execution.
    """

    # People
    PERSON = "person"

    # Systems (subtypes of SYSTEM)
    SYSTEM = "system"
    SERVICE = "service"
    DATABASE = "database"
    API = "api"

    # Concepts (subtypes of CONCEPT)
    CONCEPT = "concept"
    TECHNOLOGY = "technology"
    FRAMEWORK = "framework"
    PATTERN = "pattern"

    # Locations (subtypes of LOCATION)
    LOCATION = "location"
    REGION = "region"
    ENVIRONMENT = "environment"

    # Organisational
    PROJECT = "project"
    ORGANIZATION = "organization"

    # Agent-native types
    AGENT = "agent"
    USER = "user"
    TASK = "task"
    ACTION = "action"
    OBSERVATION = "observation"
    MEMORY = "memory"
    SESSION = "session"
    MESSAGE = "message"
    DOCUMENT = "document"
    TOOL = "tool"
    MODEL = "model"

    # Fallback
    UNKNOWN = "unknown"

    @classmethod
    def parent_type(cls, entity_type: EntityType) -> EntityType:
        """Return the parent category for a subtype."""
        _parents: dict[EntityType, EntityType] = {
            # System subtypes
            cls.SERVICE: cls.SYSTEM,
            cls.DATABASE: cls.SYSTEM,
            cls.API: cls.SYSTEM,
            # Concept subtypes
            cls.TECHNOLOGY: cls.CONCEPT,
            cls.FRAMEWORK: cls.CONCEPT,
            cls.PATTERN: cls.CONCEPT,
            # Location subtypes
            cls.REGION: cls.LOCATION,
            cls.ENVIRONMENT: cls.LOCATION,
            # Agent-native: USER is a subtype of PERSON
            cls.USER: cls.PERSON,
            # TASK, ACTION, OBSERVATION are autonomous — no parent
        }
        return _parents.get(entity_type, entity_type)


# ---------------------------------------------------------------------------
# Relationship types — infra + agent-operational predicates
# ---------------------------------------------------------------------------


class RelationType(str, Enum):
    """Fixed predicate vocabulary for knowledge-graph edges.

    Includes both **infrastructure** predicates (USES, DEPENDS_ON, …)
    and **agent-operational** predicates (PERFORMS, PRODUCES, RECALLS, …).
    """

    # Infrastructure / general
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

    # Agent-operational predicates
    PERFORMS = "PERFORMS"
    EXECUTES = "EXECUTES"
    CALLS = "CALLS"
    PRODUCES = "PRODUCES"
    OBSERVES = "OBSERVES"
    STORES = "STORES"
    RECALLS = "RECALLS"
    REFERENCES = "REFERENCES"
    DERIVED_FROM = "DERIVED_FROM"
    SAME_AS = "SAME_AS"
    PART_OF = "PART_OF"

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
    """A typed node in the knowledge graph.

    Supports multi-label typing via ``secondary_types`` and external
    grounding via ``properties`` (e.g. ``{"wikidata_id": "Q..."}``)
    """

    name: str
    entity_type: EntityType = EntityType.UNKNOWN
    secondary_types: list[EntityType] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""

    @property
    def canonical_name(self) -> str:
        """Normalised lowercase name used as the graph key."""
        return self.name.strip().lower().replace(" ", "_")

    @property
    def all_types(self) -> list[EntityType]:
        """Primary type followed by secondary types (deduplicated)."""
        seen = {self.entity_type}
        result = [self.entity_type]
        for t in self.secondary_types:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result


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


@dataclass(slots=True)
class TypeScore:
    """Ranked entity type candidate with provenance."""

    entity_type: EntityType
    confidence: float  # 0.0 – 1.0
    signal: str  # which signal produced this score


# ---------------------------------------------------------------------------
# Convenience constant: the set of agent-native entity types
# ---------------------------------------------------------------------------

AGENT_NATIVE_TYPES: frozenset[EntityType] = frozenset({
    EntityType.AGENT,
    EntityType.USER,
    EntityType.TASK,
    EntityType.ACTION,
    EntityType.OBSERVATION,
    EntityType.MEMORY,
    EntityType.SESSION,
    EntityType.MESSAGE,
    EntityType.DOCUMENT,
    EntityType.TOOL,
    EntityType.MODEL,
})

# Convenience: the set of agent-operational relation types
AGENT_RELATION_TYPES: frozenset[RelationType] = frozenset({
    RelationType.PERFORMS,
    RelationType.EXECUTES,
    RelationType.CALLS,
    RelationType.PRODUCES,
    RelationType.OBSERVES,
    RelationType.STORES,
    RelationType.RECALLS,
    RelationType.REFERENCES,
    RelationType.DERIVED_FROM,
    RelationType.SAME_AS,
    RelationType.PART_OF,
})

# Pre-compiled regex for canonical name normalisation
_CANONICAL_RE = re.compile(r"\s+")
