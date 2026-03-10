"""Domain/range constraints and validation for knowledge-graph edges.

Defines which entity types are allowed as subject and object for each
relation predicate.  ``validate_triple_types()`` checks a candidate
triple against these rules and returns a diagnostic.

Design
------
``RELATION_RULES`` is the single source of truth.  Each entry maps a
``RelationType`` to the sets of ``EntityType`` values permitted as the
subject and object of that relation.  Types not listed in the rule are
*allowed* if no rule exists for the predicate (open-world by default)
but *rejected* if a rule exists and the type is not in the allowed set.

The validator does **not** block insertion — callers decide whether to
discard, demote confidence, or log a warning.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ontology_types import EntityType, RelationType

# ---------------------------------------------------------------------------
# Relation domain/range constraint table
# ---------------------------------------------------------------------------

RELATION_RULES: dict[RelationType, dict[str, frozenset[EntityType]]] = {
    # Infrastructure predicates
    RelationType.WORKS_ON: {
        "subject": frozenset({EntityType.PERSON, EntityType.AGENT, EntityType.USER}),
        "object": frozenset({
            EntityType.PROJECT, EntityType.TASK, EntityType.SYSTEM,
            EntityType.SERVICE, EntityType.UNKNOWN,
        }),
    },
    RelationType.WORKS_WITH: {
        "subject": frozenset({EntityType.PERSON, EntityType.AGENT, EntityType.USER}),
        "object": frozenset({
            EntityType.PERSON, EntityType.AGENT, EntityType.USER,
            EntityType.TECHNOLOGY, EntityType.FRAMEWORK, EntityType.UNKNOWN,
        }),
    },
    RelationType.USES: {
        "subject": frozenset({
            EntityType.PERSON, EntityType.AGENT, EntityType.USER,
            EntityType.SERVICE, EntityType.SYSTEM,
        }),
        "object": frozenset({
            EntityType.TOOL, EntityType.API, EntityType.DATABASE,
            EntityType.TECHNOLOGY, EntityType.FRAMEWORK, EntityType.SERVICE,
            EntityType.SYSTEM, EntityType.MODEL, EntityType.UNKNOWN,
        }),
    },
    RelationType.LOCATED_IN: {
        "subject": frozenset({
            EntityType.SYSTEM, EntityType.SERVICE, EntityType.DATABASE,
            EntityType.PERSON, EntityType.AGENT, EntityType.UNKNOWN,
        }),
        "object": frozenset({
            EntityType.LOCATION, EntityType.REGION, EntityType.ENVIRONMENT,
            EntityType.UNKNOWN,
        }),
    },
    RelationType.CAUSED_BY: {
        "subject": frozenset({
            EntityType.ACTION, EntityType.OBSERVATION, EntityType.TASK,
            EntityType.SYSTEM, EntityType.SERVICE, EntityType.UNKNOWN,
        }),
        "object": frozenset({
            EntityType.ACTION, EntityType.SYSTEM, EntityType.SERVICE,
            EntityType.PERSON, EntityType.AGENT, EntityType.CONCEPT,
            EntityType.PATTERN, EntityType.UNKNOWN,
        }),
    },
    RelationType.OWNS: {
        "subject": frozenset({
            EntityType.PERSON, EntityType.AGENT, EntityType.USER,
            EntityType.ORGANIZATION,
        }),
        "object": frozenset({
            EntityType.PROJECT, EntityType.SYSTEM, EntityType.SERVICE,
            EntityType.DOCUMENT, EntityType.UNKNOWN,
        }),
    },
    RelationType.DEPENDS_ON: {
        "subject": frozenset({
            EntityType.SYSTEM, EntityType.SERVICE, EntityType.API,
            EntityType.PROJECT, EntityType.TASK, EntityType.UNKNOWN,
        }),
        "object": frozenset({
            EntityType.SYSTEM, EntityType.SERVICE, EntityType.API,
            EntityType.DATABASE, EntityType.TECHNOLOGY, EntityType.UNKNOWN,
        }),
    },
    RelationType.SUPERSEDES: {
        "subject": frozenset({
            EntityType.SYSTEM, EntityType.SERVICE, EntityType.TECHNOLOGY,
            EntityType.MODEL, EntityType.DOCUMENT, EntityType.UNKNOWN,
        }),
        "object": frozenset({
            EntityType.SYSTEM, EntityType.SERVICE, EntityType.TECHNOLOGY,
            EntityType.MODEL, EntityType.DOCUMENT, EntityType.UNKNOWN,
        }),
    },
    RelationType.CONSTRAINED_BY: {
        "subject": frozenset({
            EntityType.SYSTEM, EntityType.SERVICE, EntityType.PROJECT,
            EntityType.TASK, EntityType.UNKNOWN,
        }),
        "object": frozenset({
            EntityType.CONCEPT, EntityType.PATTERN, EntityType.TECHNOLOGY,
            EntityType.UNKNOWN,
        }),
    },
    # Agent-operational predicates
    RelationType.PERFORMS: {
        "subject": frozenset({EntityType.AGENT, EntityType.USER, EntityType.PERSON}),
        "object": frozenset({EntityType.ACTION, EntityType.TASK, EntityType.UNKNOWN}),
    },
    RelationType.EXECUTES: {
        "subject": frozenset({EntityType.AGENT, EntityType.SYSTEM, EntityType.SERVICE}),
        "object": frozenset({
            EntityType.TASK, EntityType.ACTION, EntityType.TOOL, EntityType.UNKNOWN,
        }),
    },
    RelationType.CALLS: {
        "subject": frozenset({
            EntityType.AGENT, EntityType.SERVICE, EntityType.SYSTEM,
        }),
        "object": frozenset({
            EntityType.TOOL, EntityType.API, EntityType.SERVICE, EntityType.UNKNOWN,
        }),
    },
    RelationType.PRODUCES: {
        "subject": frozenset({
            EntityType.AGENT, EntityType.TOOL, EntityType.ACTION, EntityType.SYSTEM,
        }),
        "object": frozenset({
            EntityType.OBSERVATION, EntityType.DOCUMENT, EntityType.MESSAGE,
            EntityType.MEMORY, EntityType.UNKNOWN,
        }),
    },
    RelationType.OBSERVES: {
        "subject": frozenset({EntityType.AGENT, EntityType.USER, EntityType.PERSON}),
        "object": frozenset({
            EntityType.OBSERVATION, EntityType.ACTION, EntityType.SYSTEM,
            EntityType.UNKNOWN,
        }),
    },
    RelationType.STORES: {
        "subject": frozenset({EntityType.AGENT, EntityType.SYSTEM, EntityType.SERVICE}),
        "object": frozenset({
            EntityType.MEMORY, EntityType.DOCUMENT, EntityType.OBSERVATION,
            EntityType.UNKNOWN,
        }),
    },
    RelationType.RECALLS: {
        "subject": frozenset({EntityType.AGENT, EntityType.USER}),
        "object": frozenset({
            EntityType.MEMORY, EntityType.OBSERVATION, EntityType.DOCUMENT,
            EntityType.UNKNOWN,
        }),
    },
    RelationType.REFERENCES: {
        "subject": frozenset({
            EntityType.DOCUMENT, EntityType.MESSAGE, EntityType.MEMORY,
            EntityType.OBSERVATION, EntityType.UNKNOWN,
        }),
        "object": frozenset(EntityType),  # anything can be referenced
    },
    RelationType.DERIVED_FROM: {
        "subject": frozenset({
            EntityType.MEMORY, EntityType.OBSERVATION, EntityType.DOCUMENT,
            EntityType.MODEL, EntityType.UNKNOWN,
        }),
        "object": frozenset({
            EntityType.MEMORY, EntityType.OBSERVATION, EntityType.DOCUMENT,
            EntityType.MESSAGE, EntityType.SESSION, EntityType.UNKNOWN,
        }),
    },
    RelationType.SAME_AS: {
        # Symmetric — any type can be linked to itself
        "subject": frozenset(EntityType),
        "object": frozenset(EntityType),
    },
    RelationType.PART_OF: {
        "subject": frozenset({
            EntityType.SERVICE, EntityType.API, EntityType.DATABASE,
            EntityType.TOOL, EntityType.TASK, EntityType.ACTION,
            EntityType.PERSON, EntityType.AGENT, EntityType.UNKNOWN,
        }),
        "object": frozenset({
            EntityType.SYSTEM, EntityType.PROJECT, EntityType.ORGANIZATION,
            EntityType.SESSION, EntityType.TASK, EntityType.UNKNOWN,
        }),
    },
    # RELATED_TO and MENTIONS are unconstrained — catch-all predicates
}


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TripleValidation:
    """Result of validating a triple against relation constraints."""

    valid: bool
    predicate: RelationType
    subject_type: EntityType
    object_type: EntityType
    reason: str = ""


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_triple_types(
    predicate: RelationType,
    subject_type: EntityType,
    object_type: EntityType,
) -> TripleValidation:
    """Check whether a triple's types satisfy the domain/range constraints.

    Returns ``TripleValidation(valid=True, ...)`` if:
    - no rule exists for the predicate (open-world default), **or**
    - both subject and object types are in the allowed sets.

    Returns ``valid=False`` with a descriptive ``reason`` otherwise.
    """
    rule = RELATION_RULES.get(predicate)
    if rule is None:
        return TripleValidation(
            valid=True,
            predicate=predicate,
            subject_type=subject_type,
            object_type=object_type,
            reason="no constraint defined",
        )

    allowed_subjects = rule.get("subject", frozenset())
    allowed_objects = rule.get("object", frozenset())

    subject_ok = subject_type in allowed_subjects
    object_ok = object_type in allowed_objects

    if subject_ok and object_ok:
        return TripleValidation(
            valid=True,
            predicate=predicate,
            subject_type=subject_type,
            object_type=object_type,
        )

    parts: list[str] = []
    if not subject_ok:
        allowed = ", ".join(sorted(t.value for t in allowed_subjects))
        parts.append(f"subject type '{subject_type.value}' not in allowed {{{allowed}}}")
    if not object_ok:
        allowed = ", ".join(sorted(t.value for t in allowed_objects))
        parts.append(f"object type '{object_type.value}' not in allowed {{{allowed}}}")

    return TripleValidation(
        valid=False,
        predicate=predicate,
        subject_type=subject_type,
        object_type=object_type,
        reason="; ".join(parts),
    )
