"""Backward-compatible facade for the ontology subsystem.

This module re-exports all public symbols from the four specialised
sub-modules so that existing ``from .ontology import X`` statements
continue to work unmodified:

- **ontology_types** — Enums (``EntityType``, ``RelationType``),
  dataclasses (``Entity``, ``Relationship``, ``Triple``, ``TypeScore``),
  and convenience constants.
- **ontology_rules** — Domain/range constraints (``RELATION_RULES``,
  ``validate_triple_types``, ``TripleValidation``).
- **entity_classifier** — Multi-signal scoring classifier and
  predicate-based type refinement.
- **entity_linker** — Alias resolution and entity normalisation.
"""

from __future__ import annotations

# -- Entity classification -------------------------------------------------
from .entity_classifier import (
    classify_entity_type,
    classify_entity_type_scored,
    refine_type_from_predicate,
)

# -- Entity linking --------------------------------------------------------
from .entity_linker import register_alias, resolve_alias

# -- Relation constraints --------------------------------------------------
from .ontology_rules import (
    RELATION_RULES,
    TripleValidation,
    validate_triple_types,
)

# -- Schema types ----------------------------------------------------------
from .ontology_types import (
    AGENT_NATIVE_TYPES,
    AGENT_RELATION_TYPES,
    Entity,
    EntityType,
    Relationship,
    RelationType,
    Triple,
    TypeScore,
)

__all__ = [
    # Types
    "EntityType",
    "RelationType",
    "Entity",
    "Relationship",
    "Triple",
    "TypeScore",
    "AGENT_NATIVE_TYPES",
    "AGENT_RELATION_TYPES",
    # Rules
    "RELATION_RULES",
    "TripleValidation",
    "validate_triple_types",
    # Classifier
    "classify_entity_type",
    "classify_entity_type_scored",
    "refine_type_from_predicate",
    # Linker
    "resolve_alias",
    "register_alias",
]
