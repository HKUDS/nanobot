"""Instance identity and CLI path selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_home_path: Path | None = None


@dataclass(frozen=True)
class InstancePaths:
    home: Path
    config_path: Path

    @classmethod
    def resolve(
        cls, config_path: Path | None = None, *, home: Path | None = None,
    ) -> InstancePaths:
        """Resolve selectors without creating directories or changing CLI selection."""
        config = config_path.expanduser().resolve() if config_path is not None else None
        root = (
            home.expanduser().resolve() if home is not None
            else config.parent if config is not None
            else (Path.home() / ".nanobot").resolve()
        )
        return cls(root, config if config is not None else (root / "config.json").resolve())


def set_home_path(path: Path | None) -> None:
    """Select the explicit instance root for the current CLI invocation."""
    global _home_path
    _home_path = path.expanduser().resolve() if path is not None else None


def get_selected_home_path() -> Path | None:
    """Return the explicit instance root, if one was selected."""
    return _home_path


def get_instance_paths() -> InstancePaths:
    """Snapshot the current CLI selectors without filesystem writes."""
    from nanobot.config.loader import get_selected_config_path

    return InstancePaths.resolve(get_selected_config_path(), home=_home_path)


def get_home_path() -> Path:
    """Return the current CLI instance root."""
    return get_instance_paths().home
