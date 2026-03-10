"""Tests for the ontology module (entity types, relationships, triples)."""

from __future__ import annotations

from nanobot.agent.memory.ontology import (
    Entity,
    EntityType,
    Relationship,
    RelationType,
    Triple,
    TypeScore,
    classify_entity_type,
    classify_entity_type_scored,
    refine_type_from_predicate,
    resolve_alias,
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
        assert refine_type_from_predicate(
            EntityType.UNKNOWN, RelationType.WORKS_ON, is_subject=True,
        ) == EntityType.PERSON

    def test_refines_unknown_object(self) -> None:
        # LOCATED_IN object → LOCATION
        assert refine_type_from_predicate(
            EntityType.UNKNOWN, RelationType.LOCATED_IN, is_subject=False,
        ) == EntityType.LOCATION

    def test_preserves_known_type(self) -> None:
        # Already classified — should not overwrite
        assert refine_type_from_predicate(
            EntityType.DATABASE, RelationType.WORKS_ON, is_subject=True,
        ) == EntityType.DATABASE

    def test_no_hint_stays_unknown(self) -> None:
        assert refine_type_from_predicate(
            EntityType.UNKNOWN, RelationType.RELATED_TO, is_subject=True,
        ) == EntityType.UNKNOWN
