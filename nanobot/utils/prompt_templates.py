"""Load and render agent system prompt templates (Jinja2) under nanobot/templates/.

Agent prompts live in ``templates/agent/`` (pass names like ``agent/identity.md``).
Shared copy lives under ``agent/_snippets/`` and is included via
``{% include 'agent/_snippets/....md' %}``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"


@lru_cache
def _environment() -> Environment:
    # Plain-text prompts: do not HTML-escape variable values.
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_ROOT)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(name: str, *, strip: bool = False, **kwargs: Any) -> str:
    """Render ``name`` (e.g. ``agent/identity.md``, ``agent/platform_policy.md``) under ``templates/``.

    Use ``strip=True`` for single-line user-facing strings when the file ends
    with a trailing newline you do not want preserved.
    """
    text = _environment().get_template(name).render(**kwargs)
    return text.rstrip() if strip else text


def render_template_from_path(path: Path, *, strip: bool = False, **kwargs: Any) -> str:
    """Render a Jinja template at an arbitrary absolute path.

    Used for user-supplied prompt overrides (e.g. Dream custom templates from
    ``DreamConfig.phase1_template``). Reuses the shared Jinja ``Environment``
    so ``{% include %}`` of builtin snippets continues to work.
    """
    source = path.read_text(encoding="utf-8")
    text = _environment().from_string(source).render(**kwargs)
    return text.rstrip() if strip else text
