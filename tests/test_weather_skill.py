from pathlib import Path

import yaml

SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "skills"
    / "weather"
    / "SKILL.md"
)


def _parse_frontmatter(text):
    assert text.startswith("---\n")
    _, frontmatter, _ = text.split("---\n", 2)
    return yaml.safe_load(frontmatter)


def test_weather_skill_file_exists():
    assert SKILL_PATH.is_file()


def test_weather_skill_frontmatter():
    metadata = _parse_frontmatter(SKILL_PATH.read_text(encoding="utf-8"))
    assert metadata["name"] == "weather"
    assert metadata["description"].strip()


def test_weather_skill_description_mentions_trigger_terms():
    metadata = _parse_frontmatter(SKILL_PATH.read_text(encoding="utf-8"))
    description = metadata["description"].lower()
    assert "weather" in description
    assert any(term in description for term in ("temperature", "rain", "forecast"))
