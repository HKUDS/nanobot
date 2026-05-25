"""Tests for the fleet REGISTRY.md parser/writer."""

from __future__ import annotations

import pytest

from nanobot.fleet import AgentRecord, Registry


def test_load_missing_file(tmp_path):
    reg = Registry(tmp_path / "REGISTRY.md")
    assert reg.agents == []


def test_round_trip_single_agent(tmp_path):
    path = tmp_path / "REGISTRY.md"
    reg = Registry(path)
    reg.add(AgentRecord(
        name="peewee", repo="phelps-sg/agent-peewee", host="sphelps.net",
        description="family assistant",
    ))
    reg.save()
    # Reload
    reg2 = Registry(path)
    assert len(reg2.agents) == 1
    a = reg2.agents[0]
    assert a.name == "peewee"
    assert a.repo == "phelps-sg/agent-peewee"
    assert a.host == "sphelps.net"
    assert a.status == "active"
    assert a.description == "family assistant"
    assert a.created  # auto-populated to today


def test_preserves_freeform_trailing_text(tmp_path):
    path = tmp_path / "REGISTRY.md"
    path.write_text(
        "# Agent Fleet Registry\n\n"
        "| Name | Repo | Host | Created | Status | Description |\n"
        "|---|---|---|---|---|---|\n"
        "| iroh | phelps-sg/agent-iroh | sphelps.net | 2026-05-22 | active | Glyn's assistant |\n"
        "\n"
        "## Notes\n\n"
        "Hand-written observations live here.\n"
    )
    reg = Registry(path)
    assert reg.agents[0].name == "iroh"
    reg.save()
    after = path.read_text()
    assert "## Notes" in after
    assert "Hand-written observations live here." in after


def test_add_rejects_duplicate(tmp_path):
    reg = Registry(tmp_path / "REGISTRY.md")
    reg.add(AgentRecord(name="peewee"))
    with pytest.raises(ValueError):
        reg.add(AgentRecord(name="peewee"))


def test_update_changes_fields(tmp_path):
    reg = Registry(tmp_path / "REGISTRY.md")
    reg.add(AgentRecord(name="peewee", status="active"))
    reg.update("peewee", status="archived", description="moved on")
    a = reg.get("peewee")
    assert a.status == "archived"
    assert a.description == "moved on"


def test_update_missing_raises(tmp_path):
    reg = Registry(tmp_path / "REGISTRY.md")
    with pytest.raises(KeyError):
        reg.update("nobody", status="archived")


def test_remove(tmp_path):
    reg = Registry(tmp_path / "REGISTRY.md")
    reg.add(AgentRecord(name="x"))
    reg.add(AgentRecord(name="y"))
    reg.remove("x")
    assert [a.name for a in reg.agents] == ["y"]


def test_active_filter(tmp_path):
    reg = Registry(tmp_path / "REGISTRY.md")
    reg.add(AgentRecord(name="a", status="active"))
    reg.add(AgentRecord(name="b", status="archived"))
    assert [a.name for a in reg.active()] == ["a"]


def test_pipes_in_description_are_escaped(tmp_path):
    path = tmp_path / "REGISTRY.md"
    reg = Registry(path)
    reg.add(AgentRecord(name="x", description="weather | finance"))
    reg.save()
    content = path.read_text()
    assert "weather \\| finance" in content
    # And reload still works (pipe escapes are not unescaped, but won't break parsing).
    reg2 = Registry(path)
    assert reg2.agents[0].name == "x"
