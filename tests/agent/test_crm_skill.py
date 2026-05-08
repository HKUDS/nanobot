from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path("nanobot/skills/crm-opportunity-intelligence/SKILL.md")


def test_crm_skill_documents_mcp_first_usage_and_safety_boundaries() -> None:
    text = SKILL_PATH.read_text()

    required = [
        "MCP server",
        "deterministic metrics",
        "evidence traces",
        "no CRM writeback",
        "daily report",
        "weekly report",
        "dashboard summary",
        "synthetic or mocked data",
    ]

    missing = [item for item in required if item not in text]
    assert not missing


def test_crm_skill_contains_no_real_data_or_secrets() -> None:
    text = SKILL_PATH.read_text().lower()

    forbidden = ["token=", "secret=", "password=", "真实", "customer.com", "corp.com"]
    assert all(marker not in text for marker in forbidden)


def test_crm_skill_does_not_require_core_agent_tool_registration() -> None:
    text = SKILL_PATH.read_text()

    assert "do not register a native built-in CRM tool" in text
    assert "nanobot/agent/loop.py" in text
