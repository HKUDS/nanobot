import tomllib
from pathlib import Path

import yaml

from nanobot.agent.skills import SkillsLoader

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


def test_weather_skill_is_not_registered_as_builtin(tmp_path):
    loader = SkillsLoader(workspace=tmp_path)
    builtin_weather = [
        entry
        for entry in loader.list_skills(filter_unavailable=False)
        if entry["name"] == "weather" and entry["source"] == "builtin"
    ]
    assert builtin_weather == []


def test_examples_skills_are_packaged():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    build_targets = pyproject["tool"]["hatch"]["build"]["targets"]

    assert "examples/" in build_targets["sdist"]["include"]
    assert build_targets["wheel"]["force-include"]["examples"] == "examples"
