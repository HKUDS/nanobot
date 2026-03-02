"""Account profile management — backed by the existing config.json.

Named accounts are stored under ``agents.accounts`` in config.json so there
is no separate profiles.json file to maintain.  This module is a thin
adapter that converts between the ``AccountEntry`` schema type and the
``Profile`` data-class expected by the rest of the code.
"""

from __future__ import annotations

from dataclasses import dataclass

from nanobot.config.loader import load_config, save_config


@dataclass
class Profile:
    """A resolved named AI account."""

    name: str
    model: str
    api_key: str
    api_base: str | None = None


class ProfileManager:
    """Read/write named accounts from config.json's ``agents.accounts`` dict."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_profiles(self) -> list[Profile]:
        """Return all saved accounts."""
        config = load_config()
        return [
            Profile(name=name, model=entry.model, api_key=entry.api_key, api_base=entry.api_base)
            for name, entry in config.agents.accounts.items()
        ]

    def get_profile(self, name: str) -> Profile | None:
        """Return a single account by name, or *None* if not found."""
        config = load_config()
        entry = config.agents.accounts.get(name)
        if entry is None:
            return None
        return Profile(name=name, model=entry.model, api_key=entry.api_key, api_base=entry.api_base)

    def add_profile(self, profile: Profile) -> None:
        """Persist an account (insert or overwrite)."""
        from nanobot.config.schema import AccountEntry
        config = load_config()
        config.agents.accounts[profile.name] = AccountEntry(
            model=profile.model,
            api_key=profile.api_key,
            api_base=profile.api_base,
        )
        save_config(config)

    def remove_profile(self, name: str) -> bool:
        """Remove an account. Returns *True* if it existed, *False* otherwise."""
        config = load_config()
        if name not in config.agents.accounts:
            return False
        del config.agents.accounts[name]
        save_config(config)
        return True
