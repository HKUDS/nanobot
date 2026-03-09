"""Tests for the ontology module (entity types, relationships, triples)."""

from __future__ import annotations

from nanobot.agent.memory.ontology import (
    Entity,
    EntityType,
    Relationship,
    RelationType,
    Triple,
    classify_entity_type,
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
