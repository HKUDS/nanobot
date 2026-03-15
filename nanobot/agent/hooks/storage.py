"""Persistent storage for hook state."""

import json
from pathlib import Path


class HookStorage:
    """Persistent storage for hook state."""

    def __init__(self, workspace: Path):
        self.state_file = workspace / "hooks" / "state.json"
        self._state: dict = {}
        self._load()

    def _load(self) -> None:
        """Load state from disk."""
        if self.state_file.exists():
            self._state = json.loads(self.state_file.read_text())
        else:
            self._state = {"disabled_skills": []}

    def _save(self) -> None:
        """Save state to disk."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self._state, indent=2))

    def get_disabled_skills(self) -> set[str]:
        """Get set of disabled skill names."""
        return set(self._state.get("disabled_skills", []))

    def set_skill_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a skill."""
        disabled = set(self._state.get("disabled_skills", []))
        if enabled:
            disabled.discard(name)
        else:
            disabled.add(name)
        self._state["disabled_skills"] = sorted(disabled)
        self._save()

    def is_skill_disabled(self, name: str) -> bool:
        """Check if a skill is disabled."""
        return name in self.get_disabled_skills()
