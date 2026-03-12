"""Entity linking — alias resolution and name normalisation.

Responsible for mapping shorthand names, abbreviations, and spelling
variants to their canonical form *before* the classifier runs.

Separated from the classifier so that alias tables can grow
independently (e.g. populated from profile data or external sources)
without touching scoring logic.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Alias map — shorthand → canonical name
# ---------------------------------------------------------------------------

_ALIAS_MAP: dict[str, str] = {
    # Databases
    "pg": "postgresql",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "es": "elasticsearch",
    # Technologies
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "tf": "terraform",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "python3": "python",
    "gh": "github",
    "gh actions": "github actions",
    # Environments
    "prod": "production",
    "dev": "development",
    "preprod": "pre-production",
    "pre-prod": "pre-production",
}


def resolve_alias(name: str) -> str:
    """Map known shorthand/alias to its canonical entity name.

    Returns the original name (stripped) if no alias is registered.
    """
    return _ALIAS_MAP.get(name.strip().lower(), name.strip())


def register_alias(alias: str, canonical: str) -> None:
    """Add a runtime alias mapping (e.g. from profile data).

    Overwrites any existing entry for the same alias key.
    """
    _ALIAS_MAP[alias.strip().lower()] = canonical.strip()
