"""Secret reference resolver for configuration.

Supports {env:VARIABLE_NAME} syntax to reference environment variables.
"""

import os
import re
from typing import Any

# Pattern matches {env:VAR_NAME} where VAR_NAME follows env var naming conventions
_REF_PATTERN = re.compile(r"\{env:([A-Z_][A-Z0-9_]*)\}")


def resolve_env_vars(value: str) -> str:
    """Resolve {env:VAR} references in a string.

    Args:
        value: String that may contain {env:VAR} references.

    Returns:
        String with all {env:VAR} references replaced by their values.
        Missing env vars are left unchanged.
    """

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            return match.group(0)
        return env_value

    return _REF_PATTERN.sub(replacer, value)


def has_env_ref(value: str) -> bool:
    """Return True if string contains at least one {env:VAR} reference."""
    return bool(_REF_PATTERN.search(value))


def resolve_config(obj: Any) -> Any:
    """Recursively resolve {env:VAR} references in a configuration object.

    Args:
        obj: Configuration value (str, dict, list, or other).

    Returns:
        Configuration with all {env:VAR} references resolved.
    """
    if isinstance(obj, str):
        return resolve_env_vars(obj)
    if isinstance(obj, dict):
        return {k: resolve_config(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_config(item) for item in obj]
    return obj
