"""Optional dependency checks for GEPA / DSPy (``nanobot-ai[evolution]``)."""

from __future__ import annotations

_EVOLUTION_INSTALL_HINT = (
    "GEPA evolution requires optional dependencies. "
    "Install with: pip install nanobot-ai[evolution]"
)


def evolution_extra_available() -> bool:
    """Return True when DSPy is installed and exposes ``GEPA``."""
    try:
        import dspy
    except ImportError:
        return False
    return hasattr(dspy, "GEPA")


def require_evolution_extra() -> str | None:
    """Return an install hint when the evolution extra is missing, else ``None``."""
    if evolution_extra_available():
        return None
    return _EVOLUTION_INSTALL_HINT
