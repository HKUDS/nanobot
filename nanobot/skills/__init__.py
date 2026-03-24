"""Built-in skills for the nanobot agent framework.

Skills are the plugin extension system for nanobot.  Each skill lives in a
sub-directory and is defined by a ``SKILL.md`` file with YAML frontmatter
containing metadata (name, description, tools) followed by Markdown
instructions that are injected into the agent's system prompt when the
skill is activated.

Skill discovery is handled by :class:`~nanobot.agent.skills.SkillsLoader`,
which scans both built-in skills (this package) and user workspace skills.

Optionally, a skill directory may include a ``tools.py`` module that defines
custom :class:`~nanobot.tools.base.Tool` subclasses.  These are
auto-registered when the skill is loaded.

See ``nanobot/skills/weather/`` for a minimal reference implementation.
"""

from __future__ import annotations

__all__: list[str] = []
