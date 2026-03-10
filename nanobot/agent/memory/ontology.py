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

import re
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
# Entity type classification — multi-signal scoring system
#
# Replaces single-pass substring matching with layered signals:
#   1. Regex patterns    — structured formats (region codes)          → 0.95
#   2. Token keywords    — known system/tech names (word-boundary)    → 0.85
#   3. Phrase keywords   — multi-word compound names (substring)      → 0.85
#   4. Suffix patterns   — trailing patterns (" team", " service")   → 0.75
#   5. Role keywords     — person-indicator words ("engineer", …)    → 0.70
#   6. Capitalisation    — proper nouns not matching system terms      → 0.45
#
# classify_entity_type() remains backward-compatible (returns top type).
# classify_entity_type_scored() exposes ranked candidates + confidence.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TypeScore:
    """Ranked entity type candidate with provenance."""

    entity_type: EntityType
    confidence: float  # 0.0 – 1.0
    signal: str  # which signal produced this score


# ── Signal 1: Regex patterns (highest confidence) ────────────────────────

_REGEX_PATTERNS: list[tuple[EntityType, re.Pattern[str]]] = [
    # Cloud region codes: us-east-1, eu-west-2, ap-southeast-1, …
    (EntityType.REGION, re.compile(
        r"\b[a-z]{2}-"
        r"(east|west|north|south|central|northeast|southeast|northwest|southwest)"
        r"-\d+\b"
    )),
]


# ── Signal 2: Token keyword sets (good confidence) ──────────────────────
#
# Each keyword is matched as an exact token (word-boundary) against the
# tokenised entity name — NOT as a substring.

_KEYWORD_SETS: list[tuple[EntityType, frozenset[str]]] = [
    (EntityType.REGION, frozenset({
        "region", "zone", "datacenter",
        # Cloud-provider region prefixes (complement regex for partial refs)
        "eu-west", "eu-central", "us-east", "us-west",
        "ap-south", "ap-northeast", "ap-southeast",
        "me-south", "af-south", "ca-central", "sa-east",
    })),
    (EntityType.ENVIRONMENT, frozenset({
        "production", "staging", "development", "local",
        "canary", "sandbox", "ci",
    })),
    (EntityType.DATABASE, frozenset({
        "postgresql", "postgres", "mysql", "mariadb", "redis", "memcached",
        "mongodb", "mongo", "sqlite", "qdrant", "neo4j", "elasticsearch",
        "opensearch", "dynamodb", "cassandra", "cockroachdb", "clickhouse",
        "influxdb", "supabase", "pinecone", "weaviate", "milvus", "chromadb",
    })),
    (EntityType.API, frozenset({
        "api", "endpoint", "graphql", "grpc", "webhook", "openapi", "swagger",
    })),
    (EntityType.SERVICE, frozenset({
        "gateway", "proxy", "broker", "queue", "worker", "scheduler",
        "daemon", "sidecar", "ingress",
    })),
    (EntityType.FRAMEWORK, frozenset({
        "django", "flask", "fastapi", "express", "nestjs", "spring", "rails",
        "laravel", "react", "vue", "angular", "svelte", "nextjs", "nuxt",
        "pydantic", "sqlalchemy", "celery", "airflow", "langchain",
    })),
    (EntityType.TECHNOLOGY, frozenset({
        "python", "javascript", "typescript", "golang", "rust", "java",
        "docker", "kubernetes", "terraform", "ansible", "helm", "pulumi",
        "oauth", "oauth2", "saml", "jwt",
        "kafka", "rabbitmq", "nats",
        "nginx", "caddy", "traefik", "envoy",
        "prometheus", "grafana", "datadog", "sentry",
        "git", "github", "gitlab",
    })),
    (EntityType.PATTERN, frozenset({
        "pattern", "strategy", "singleton", "observer", "decorator", "factory",
        "circuit-breaker", "saga", "cqrs",
    })),
    (EntityType.PROJECT, frozenset({
        "project", "sprint", "epic", "milestone", "roadmap", "rollout",
    })),
    (EntityType.ORGANIZATION, frozenset({
        "company", "department", "division", "org", "organisation", "organization",
    })),
]


# ── Signal 3: Multi-word phrase keywords (substring match) ──────────────

_PHRASE_KEYWORDS: list[tuple[EntityType, tuple[str, ...]]] = [
    (EntityType.TECHNOLOGY, ("github actions", "ci/cd")),
    (EntityType.ORGANIZATION, ("platform team", "infrastructure team", "sre team")),
]


# ── Signal 4: Suffix patterns (moderate confidence) ─────────────────────

_SUFFIX_PATTERNS: list[tuple[EntityType, tuple[str, ...]]] = [
    (EntityType.ORGANIZATION, (" team", " squad", " guild", " group")),
    (EntityType.SERVICE, (" service", " worker", " daemon", " server")),
    (EntityType.DATABASE, (" db", " database", " store", " cache")),
    (EntityType.API, (" api", " endpoint")),
    (EntityType.PROJECT, (" project", " rollout")),
]


# ── Signal 5: Person detection ──────────────────────────────────────────

_PERSON_ROLE_KEYWORDS: frozenset[str] = frozenset({
    "user", "manager", "lead", "engineer", "developer", "architect",
    "admin", "analyst", "scientist", "designer", "director",
    "coordinator", "specialist", "consultant", "maintainer",
    "contributor", "reviewer", "owner",
})

# Words never treated as person names by the capitalisation heuristic.
_CAPITALIZATION_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "for", "in", "on", "to",
    "of", "at", "by", "is", "it", "as", "if", "no", "not", "so",
    "up", "out", "off", "all", "new", "old", "big", "top", "low",
    "set", "get", "run", "add", "use", "try", "may", "can", "let",
    "any", "our", "how", "why", "who", "what", "when", "where", "which",
    "this", "that", "with", "from", "into", "over", "just", "only",
    "each", "both", "such", "very", "also", "here", "there",
    "true", "false", "none", "null",
})

# Collect all non-person keywords so the capitalisation heuristic can
# avoid misclassifying known system terms as people.
_NON_PERSON_KEYWORDS: frozenset[str] = frozenset().union(
    *(kws for _, kws in _KEYWORD_SETS)
)


# ── Alias resolution — entity linking for deduplication ─────────────────

_ALIAS_MAP: dict[str, str] = {
    # Databases
    "pg": "postgresql", "postgres": "postgresql",
    "mongo": "mongodb", "es": "elasticsearch",
    # Technologies
    "k8s": "kubernetes", "kube": "kubernetes",
    "tf": "terraform",
    "js": "javascript", "ts": "typescript",
    "py": "python", "python3": "python",
    "gh": "github", "gh actions": "github actions",
    # Environments
    "prod": "production", "dev": "development",
    "preprod": "pre-production", "pre-prod": "pre-production",
}


def resolve_alias(name: str) -> str:
    """Map known shorthand/alias to its canonical entity name.

    Returns the original name (stripped) if no alias is registered.
    """
    return _ALIAS_MAP.get(name.strip().lower(), name.strip())


# ── Confidence tiers per signal ─────────────────────────────────────────

_CONFIDENCE: dict[str, float] = {
    "regex": 0.95,
    "keyword": 0.85,
    "phrase": 0.85,
    "suffix": 0.75,
    "role": 0.70,
    "capitalized": 0.45,
}


# ── Classifier ──────────────────────────────────────────────────────────

def classify_entity_type_scored(name: str) -> list[TypeScore]:
    """Multi-signal entity type classification with confidence scores.

    Returns ranked ``TypeScore`` candidates (descending confidence).
    Falls back to ``[TypeScore(UNKNOWN, 1.0, "no_match")]``.
    """
    raw = name.strip()
    if not raw:
        return [TypeScore(EntityType.UNKNOWN, 1.0, "empty")]

    resolved = resolve_alias(raw)
    lowered = resolved.lower()
    words = frozenset(re.findall(r"[a-z0-9][a-z0-9_\-]*", lowered))

    candidates: list[TypeScore] = []

    # 1. Regex patterns
    for etype, pattern in _REGEX_PATTERNS:
        if pattern.search(lowered):
            candidates.append(TypeScore(etype, _CONFIDENCE["regex"], "regex"))

    # 2. Token keyword matching
    for etype, kws in _KEYWORD_SETS:
        if words & kws:
            candidates.append(TypeScore(etype, _CONFIDENCE["keyword"], "keyword"))

    # 3. Multi-word phrase matching
    for etype, phrases in _PHRASE_KEYWORDS:
        if any(p in lowered for p in phrases):
            candidates.append(TypeScore(etype, _CONFIDENCE["phrase"], "phrase"))

    # 4. Suffix matching
    for etype, suffixes in _SUFFIX_PATTERNS:
        if any(lowered.endswith(s) for s in suffixes):
            candidates.append(TypeScore(etype, _CONFIDENCE["suffix"], "suffix"))

    # 5. Person role keywords
    if words & _PERSON_ROLE_KEYWORDS:
        candidates.append(TypeScore(EntityType.PERSON, _CONFIDENCE["role"], "role"))

    # 6. Capitalisation heuristic — proper noun(s) not matching system terms
    name_words = [w for w in raw.split() if len(w) >= 2]
    if name_words:
        significant = [
            w for w in name_words
            if w[0].isupper() and w.lower() not in _CAPITALIZATION_STOPWORDS
        ]
        if significant and not (words & _NON_PERSON_KEYWORDS):
            candidates.append(
                TypeScore(EntityType.PERSON, _CONFIDENCE["capitalized"], "capitalized")
            )

    if not candidates:
        return [TypeScore(EntityType.UNKNOWN, 1.0, "no_match")]

    # Deduplicate: keep highest-confidence score per entity type
    best: dict[EntityType, TypeScore] = {}
    for c in candidates:
        if c.entity_type not in best or c.confidence > best[c.entity_type].confidence:
            best[c.entity_type] = c

    return sorted(best.values(), key=lambda s: (-s.confidence, s.entity_type.value))


def classify_entity_type(name: str) -> EntityType:
    """Infer an entity type from its name using multi-signal heuristics.

    Returns ``EntityType.UNKNOWN`` when no signal fires.  Backward-compatible
    wrapper around :func:`classify_entity_type_scored`.
    """
    return classify_entity_type_scored(name)[0].entity_type


# ---------------------------------------------------------------------------
# Predicate-based type refinement
#
# When the name-based classifier returns UNKNOWN, the predicate linking
# two entities can narrow the type.  Only promotes UNKNOWN — never
# overwrites a type that was already classified with evidence.
# ---------------------------------------------------------------------------

_PREDICATE_SUBJECT_HINTS: dict[RelationType, EntityType] = {
    RelationType.WORKS_ON: EntityType.PERSON,
    RelationType.WORKS_WITH: EntityType.PERSON,
    RelationType.OWNS: EntityType.PERSON,
}

_PREDICATE_OBJECT_HINTS: dict[RelationType, EntityType] = {
    RelationType.LOCATED_IN: EntityType.LOCATION,
    RelationType.DEPENDS_ON: EntityType.SYSTEM,
    RelationType.CONSTRAINED_BY: EntityType.CONCEPT,
    RelationType.USES: EntityType.SYSTEM,
}


def refine_type_from_predicate(
    current_type: EntityType,
    predicate: RelationType,
    *,
    is_subject: bool,
) -> EntityType:
    """Refine an UNKNOWN entity type using the predicate linking it.

    Only promotes ``UNKNOWN`` → hinted type; an already-classified type
    is returned unchanged.
    """
    if current_type != EntityType.UNKNOWN:
        return current_type
    hints = _PREDICATE_SUBJECT_HINTS if is_subject else _PREDICATE_OBJECT_HINTS
    return hints.get(predicate, EntityType.UNKNOWN)
