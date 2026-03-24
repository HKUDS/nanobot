"""Tests for the ontology module (entity types, relationships, triples)."""

from __future__ import annotations

from nanobot.memory.entity_classifier import (
    classify_entity_type,
    classify_entity_type_scored,
    refine_type_from_predicate,
)
from nanobot.memory.entity_linker import resolve_alias
from nanobot.memory.ontology_rules import (
    RELATION_RULES,
    TripleValidation,
    validate_triple_types,
)
from nanobot.memory.ontology_types import (
    AGENT_NATIVE_TYPES,
    AGENT_RELATION_TYPES,
    Entity,
    EntityType,
    Relationship,
    RelationType,
    Triple,
    TypeScore,
)


class TestEntityType:
    def test_parent_types(self) -> None:
        assert EntityType.parent_type(EntityType.SERVICE) == EntityType.SYSTEM
        assert EntityType.parent_type(EntityType.DATABASE) == EntityType.SYSTEM
        assert EntityType.parent_type(EntityType.TECHNOLOGY) == EntityType.CONCEPT
        assert EntityType.parent_type(EntityType.FRAMEWORK) == EntityType.CONCEPT
        assert EntityType.parent_type(EntityType.REGION) == EntityType.LOCATION
        assert EntityType.parent_type(EntityType.ENVIRONMENT) == EntityType.LOCATION
        # Top-level types return themselves
        assert EntityType.parent_type(EntityType.PERSON) == EntityType.PERSON
        assert EntityType.parent_type(EntityType.UNKNOWN) == EntityType.UNKNOWN

    def test_agent_native_parent_types(self) -> None:
        # USER is a subtype of PERSON
        assert EntityType.parent_type(EntityType.USER) == EntityType.PERSON
        # Autonomous agent-native types return themselves
        assert EntityType.parent_type(EntityType.AGENT) == EntityType.AGENT
        assert EntityType.parent_type(EntityType.TASK) == EntityType.TASK
        assert EntityType.parent_type(EntityType.ACTION) == EntityType.ACTION
        assert EntityType.parent_type(EntityType.SESSION) == EntityType.SESSION

    def test_agent_native_types_exist(self) -> None:
        for name in (
            "AGENT",
            "USER",
            "TASK",
            "ACTION",
            "OBSERVATION",
            "MEMORY",
            "SESSION",
            "MESSAGE",
            "DOCUMENT",
            "TOOL",
            "MODEL",
        ):
            assert hasattr(EntityType, name)
            assert EntityType(name.lower()) is getattr(EntityType, name)

    def test_agent_native_types_constant(self) -> None:
        assert EntityType.AGENT in AGENT_NATIVE_TYPES
        assert EntityType.TOOL in AGENT_NATIVE_TYPES
        assert EntityType.MODEL in AGENT_NATIVE_TYPES
        assert EntityType.PERSON not in AGENT_NATIVE_TYPES

    def test_all_values_are_strings(self) -> None:
        for member in EntityType:
            assert isinstance(member.value, str)


class TestRelationType:
    def test_from_str_valid(self) -> None:
        assert RelationType.from_str("WORKS_ON") == RelationType.WORKS_ON
        assert RelationType.from_str("works on") == RelationType.WORKS_ON
        assert RelationType.from_str("  USES  ") == RelationType.USES

    def test_from_str_invalid_falls_back(self) -> None:
        assert RelationType.from_str("UNKNOWN_RELATION") == RelationType.RELATED_TO
        assert RelationType.from_str("") == RelationType.RELATED_TO

    def test_all_values_uppercase(self) -> None:
        for member in RelationType:
            assert member.value == member.value.upper()

    def test_agent_operational_relations_exist(self) -> None:
        for name in (
            "PERFORMS",
            "EXECUTES",
            "CALLS",
            "PRODUCES",
            "OBSERVES",
            "STORES",
            "RECALLS",
            "REFERENCES",
            "DERIVED_FROM",
            "SAME_AS",
            "PART_OF",
        ):
            assert hasattr(RelationType, name)

    def test_agent_relation_types_constant(self) -> None:
        assert RelationType.PERFORMS in AGENT_RELATION_TYPES
        assert RelationType.RECALLS in AGENT_RELATION_TYPES
        assert RelationType.WORKS_ON not in AGENT_RELATION_TYPES

    def test_from_str_agent_predicates(self) -> None:
        assert RelationType.from_str("PERFORMS") == RelationType.PERFORMS
        assert RelationType.from_str("derived from") == RelationType.DERIVED_FROM
        assert RelationType.from_str("PART_OF") == RelationType.PART_OF


class TestEntity:
    def test_canonical_name(self) -> None:
        e = Entity(name="Carlos Martinez")
        assert e.canonical_name == "carlos_martinez"

    def test_canonical_name_strips(self) -> None:
        e = Entity(name="  hello world  ")
        assert e.canonical_name == "hello_world"

    def test_default_values(self) -> None:
        e = Entity(name="test")
        assert e.entity_type == EntityType.UNKNOWN
        assert e.aliases == []
        assert e.properties == {}
        assert e.first_seen == ""
        assert e.last_seen == ""

    def test_secondary_types(self) -> None:
        e = Entity(
            name="Neo4j",
            entity_type=EntityType.DATABASE,
            secondary_types=[EntityType.SYSTEM, EntityType.TECHNOLOGY],
        )
        assert e.all_types == [EntityType.DATABASE, EntityType.SYSTEM, EntityType.TECHNOLOGY]

    def test_all_types_deduplicates(self) -> None:
        e = Entity(
            name="x",
            entity_type=EntityType.TECHNOLOGY,
            secondary_types=[EntityType.TECHNOLOGY, EntityType.SYSTEM],
        )
        assert e.all_types == [EntityType.TECHNOLOGY, EntityType.SYSTEM]

    def test_external_grounding(self) -> None:
        e = Entity(
            name="Python",
            entity_type=EntityType.TECHNOLOGY,
            properties={
                "wikidata_id": "Q28865",
                "external_uri": "https://www.wikidata.org/entity/Q28865",
            },
        )
        assert e.properties["wikidata_id"] == "Q28865"


class TestRelationship:
    def test_defaults(self) -> None:
        r = Relationship(
            source_id="a",
            target_id="b",
            relation_type=RelationType.WORKS_ON,
        )
        assert r.confidence == 0.7
        assert r.source_event_id == ""
        assert r.timestamp == ""
        assert r.properties == {}


class TestTriple:
    def test_to_dict(self) -> None:
        t = Triple(
            subject="Carlos",
            predicate=RelationType.WORKS_ON,
            object="Nanobot",
            confidence=0.9,
            source_event_id="evt-1",
        )
        d = t.to_dict()
        assert d["subject"] == "Carlos"
        assert d["predicate"] == "WORKS_ON"
        assert d["object"] == "Nanobot"
        assert d["confidence"] == 0.9
        assert d["source_event_id"] == "evt-1"

    def test_from_dict(self) -> None:
        data = {
            "subject": "Alice",
            "predicate": "USES",
            "object": "Python",
            "confidence": 0.8,
        }
        t = Triple.from_dict(data, source_event_id="evt-2")
        assert t.subject == "Alice"
        assert t.predicate == RelationType.USES
        assert t.object == "Python"
        assert t.confidence == 0.8
        assert t.source_event_id == "evt-2"

    def test_from_dict_invalid_predicate_falls_back(self) -> None:
        data = {"subject": "X", "predicate": "UNKNOWN", "object": "Y"}
        t = Triple.from_dict(data)
        assert t.predicate == RelationType.RELATED_TO

    def test_from_dict_confidence_clamped(self) -> None:
        t1 = Triple.from_dict({"subject": "a", "object": "b", "confidence": 2.0})
        assert t1.confidence == 1.0
        t2 = Triple.from_dict({"subject": "a", "object": "b", "confidence": -0.5})
        assert t2.confidence == 0.0

    def test_roundtrip(self) -> None:
        t = Triple(
            subject="X",
            predicate=RelationType.DEPENDS_ON,
            object="Y",
            confidence=0.6,
        )
        t2 = Triple.from_dict(t.to_dict())
        assert t2.subject == t.subject
        assert t2.predicate == t.predicate
        assert t2.object == t.object
        assert t2.confidence == t.confidence


class TestClassifyEntityType:
    def test_person(self) -> None:
        assert classify_entity_type("Carlos") == EntityType.PERSON

    def test_database(self) -> None:
        assert classify_entity_type("PostgreSQL server") == EntityType.DATABASE

    def test_framework(self) -> None:
        assert classify_entity_type("Django app") == EntityType.FRAMEWORK

    def test_region(self) -> None:
        assert classify_entity_type("eu-west-1") == EntityType.REGION

    def test_environment(self) -> None:
        assert classify_entity_type("production") == EntityType.ENVIRONMENT

    def test_technology(self) -> None:
        assert classify_entity_type("Docker container") == EntityType.TECHNOLOGY

    def test_project(self) -> None:
        assert classify_entity_type("rollout plan") == EntityType.PROJECT

    def test_unknown(self) -> None:
        assert classify_entity_type("xyzzy_placeholder") == EntityType.UNKNOWN

    def test_empty(self) -> None:
        assert classify_entity_type("") == EntityType.UNKNOWN

    def test_case_insensitive(self) -> None:
        assert classify_entity_type("REDIS") == EntityType.DATABASE


class TestClassifyEntityTypeScored:
    """Tests for the multi-signal scored classifier."""

    def test_returns_list(self) -> None:
        result = classify_entity_type_scored("Redis")
        assert isinstance(result, list)
        assert all(isinstance(s, TypeScore) for s in result)

    def test_high_confidence_for_regex(self) -> None:
        scores = classify_entity_type_scored("us-east-1")
        assert scores[0].entity_type == EntityType.REGION
        assert scores[0].confidence >= 0.9
        assert scores[0].signal == "regex"

    def test_keyword_confidence(self) -> None:
        scores = classify_entity_type_scored("PostgreSQL")
        assert scores[0].entity_type == EntityType.DATABASE
        assert scores[0].signal == "keyword"

    def test_person_via_capitalization(self) -> None:
        # Unknown proper noun should be classified as person via capitalisation
        scores = classify_entity_type_scored("Diana")
        assert scores[0].entity_type == EntityType.PERSON
        assert scores[0].signal == "capitalized"
        assert scores[0].confidence < 0.6  # low confidence — it's a heuristic

    def test_person_via_role(self) -> None:
        scores = classify_entity_type_scored("lead engineer")
        assert scores[0].entity_type == EntityType.PERSON
        assert scores[0].signal == "role"

    def test_system_keyword_beats_capitalization(self) -> None:
        # "Docker" is capitalized but should match technology, not person
        scores = classify_entity_type_scored("Docker")
        assert scores[0].entity_type == EntityType.TECHNOLOGY

    def test_suffix_pattern(self) -> None:
        scores = classify_entity_type_scored("billing team")
        assert scores[0].entity_type == EntityType.ORGANIZATION
        assert scores[0].signal == "suffix"

    def test_phrase_keyword(self) -> None:
        scores = classify_entity_type_scored("github actions pipeline")
        assert scores[0].entity_type == EntityType.TECHNOLOGY

    def test_empty_returns_unknown(self) -> None:
        scores = classify_entity_type_scored("")
        assert scores[0].entity_type == EntityType.UNKNOWN

    def test_multiple_candidates(self) -> None:
        # "Redis server" → DATABASE (keyword "redis") + SERVICE (suffix " server")
        scores = classify_entity_type_scored("Redis server")
        types = {s.entity_type for s in scores}
        assert EntityType.DATABASE in types
        assert EntityType.SERVICE in types
        # DATABASE should rank higher
        assert scores[0].entity_type == EntityType.DATABASE


class TestResolveAlias:
    def test_known_alias(self) -> None:
        assert resolve_alias("pg") == "postgresql"
        assert resolve_alias("k8s") == "kubernetes"
        assert resolve_alias("prod") == "production"

    def test_unknown_passthrough(self) -> None:
        assert resolve_alias("foobar") == "foobar"

    def test_case_insensitive(self) -> None:
        assert resolve_alias("PG") == "postgresql"
        assert resolve_alias("K8S") == "kubernetes"

    def test_strips_whitespace(self) -> None:
        assert resolve_alias("  pg  ") == "postgresql"

    def test_alias_enables_classification(self) -> None:
        # "pg" alone wouldn't match DATABASE, but alias resolves to "postgresql"
        assert classify_entity_type("pg") == EntityType.DATABASE
        assert classify_entity_type("k8s") == EntityType.TECHNOLOGY


class TestRefineTypeFromPredicate:
    def test_refines_unknown_subject(self) -> None:
        # WORKS_ON subject → PERSON
        assert (
            refine_type_from_predicate(
                EntityType.UNKNOWN,
                RelationType.WORKS_ON,
                is_subject=True,
            )
            == EntityType.PERSON
        )

    def test_refines_unknown_object(self) -> None:
        # LOCATED_IN object → LOCATION
        assert (
            refine_type_from_predicate(
                EntityType.UNKNOWN,
                RelationType.LOCATED_IN,
                is_subject=False,
            )
            == EntityType.LOCATION
        )

    def test_preserves_known_type(self) -> None:
        # Already classified — should not overwrite
        assert (
            refine_type_from_predicate(
                EntityType.DATABASE,
                RelationType.WORKS_ON,
                is_subject=True,
            )
            == EntityType.DATABASE
        )

    def test_no_hint_stays_unknown(self) -> None:
        assert (
            refine_type_from_predicate(
                EntityType.UNKNOWN,
                RelationType.RELATED_TO,
                is_subject=True,
            )
            == EntityType.UNKNOWN
        )

    def test_agent_predicate_hints(self) -> None:
        # PERFORMS subject → AGENT
        assert (
            refine_type_from_predicate(
                EntityType.UNKNOWN,
                RelationType.PERFORMS,
                is_subject=True,
            )
            == EntityType.AGENT
        )
        # STORES object → MEMORY
        assert (
            refine_type_from_predicate(
                EntityType.UNKNOWN,
                RelationType.STORES,
                is_subject=False,
            )
            == EntityType.MEMORY
        )


class TestValidateTripleTypes:
    """Tests for relation domain/range constraint validation."""

    def test_valid_works_on(self) -> None:
        result = validate_triple_types(
            RelationType.WORKS_ON,
            EntityType.PERSON,
            EntityType.PROJECT,
        )
        assert result.valid is True

    def test_invalid_works_on_subject(self) -> None:
        # DATABASE cannot be subject of WORKS_ON
        result = validate_triple_types(
            RelationType.WORKS_ON,
            EntityType.DATABASE,
            EntityType.PROJECT,
        )
        assert result.valid is False
        assert "subject" in result.reason

    def test_invalid_works_on_object(self) -> None:
        # PERSON cannot be object of WORKS_ON
        result = validate_triple_types(
            RelationType.WORKS_ON,
            EntityType.PERSON,
            EntityType.PERSON,
        )
        assert result.valid is False
        assert "object" in result.reason

    def test_unconstrained_predicate(self) -> None:
        # RELATED_TO has no constraints — always valid
        result = validate_triple_types(
            RelationType.RELATED_TO,
            EntityType.DATABASE,
            EntityType.PERSON,
        )
        assert result.valid is True

    def test_agent_relation_valid(self) -> None:
        result = validate_triple_types(
            RelationType.PERFORMS,
            EntityType.AGENT,
            EntityType.TASK,
        )
        assert result.valid is True

    def test_agent_relation_invalid(self) -> None:
        result = validate_triple_types(
            RelationType.PERFORMS,
            EntityType.DATABASE,
            EntityType.TASK,
        )
        assert result.valid is False

    def test_same_as_always_valid(self) -> None:
        # SAME_AS is symmetric and unconstrained by entity type
        result = validate_triple_types(
            RelationType.SAME_AS,
            EntityType.DATABASE,
            EntityType.TECHNOLOGY,
        )
        assert result.valid is True

    def test_validation_result_fields(self) -> None:
        result = validate_triple_types(
            RelationType.USES,
            EntityType.AGENT,
            EntityType.TOOL,
        )
        assert isinstance(result, TripleValidation)
        assert result.predicate == RelationType.USES
        assert result.subject_type == EntityType.AGENT
        assert result.object_type == EntityType.TOOL

    def test_unknown_type_passes_when_in_allowed_set(self) -> None:
        # UNKNOWN is explicitly allowed in some subject/object sets
        result = validate_triple_types(
            RelationType.WORKS_ON,
            EntityType.PERSON,
            EntityType.UNKNOWN,
        )
        assert result.valid is True

    def test_relation_rules_completeness(self) -> None:
        # Every rule should have both subject and object keys
        for rel, rule in RELATION_RULES.items():
            assert "subject" in rule, f"{rel} missing 'subject'"
            assert "object" in rule, f"{rel} missing 'object'"


class TestClassifyAgentNativeKeywords:
    """Tests for agent-native keyword classification."""

    def test_agent_keyword(self) -> None:
        assert classify_entity_type("nanobot agent") == EntityType.AGENT

    def test_tool_keyword(self) -> None:
        assert classify_entity_type("search tool") == EntityType.TOOL

    def test_model_keyword(self) -> None:
        assert classify_entity_type("gpt-4o-mini") == EntityType.MODEL

    def test_document_keyword(self) -> None:
        assert classify_entity_type("deployment runbook") == EntityType.DOCUMENT

    def test_task_keyword(self) -> None:
        assert classify_entity_type("bug fix task") == EntityType.TASK

    def test_session_keyword(self) -> None:
        assert classify_entity_type("chat session") == EntityType.SESSION
