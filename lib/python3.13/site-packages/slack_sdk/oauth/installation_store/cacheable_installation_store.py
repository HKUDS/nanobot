from logging import Logger
from typing import Optional, Dict

from slack_sdk.oauth import InstallationStore
from slack_sdk.oauth.installation_store import Bot, Installation


class CacheableInstallationStore(InstallationStore):
    underlying: InstallationStore
    cached_bots: Dict[str, Bot]
    cached_installations: Dict[str, Installation]

    def __init__(self, installation_store: InstallationStore):
        """A simple memory cache wrapper for any installation stores.

        Args:
            installation_store: The installation store to wrap
        """
        self.underlying = installation_store
        self.cached_bots = {}
        self.cached_installations = {}

    @property
    def logger(self) -> Logger:
        return self.underlying.logger

    def save(self, installation: Installation):
        # Invalidate cache data for update operations
        key = f"{installation.enterprise_id or ''}-{installation.team_id or ''}"
        if key in self.cached_bots:
            self.cached_bots.pop(key)
        key = f"{installation.enterprise_id or ''}-{installation.team_id or ''}-{installation.user_id or ''}"
        if key in self.cached_installations:
            self.cached_installations.pop(key)

        return self.underlying.save(installation)

    def save_bot(self, bot: Bot):
        # Invalidate cache data for update operations
        key = f"{bot.enterprise_id or ''}-{bot.team_id or ''}"
        if key in self.cached_bots:
            self.cached_bots.pop(key)
        return self.underlying.save_bot(bot)

    def find_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Bot]:
        if is_enterprise_install or team_id is None:
            team_id = ""
        key = f"{enterprise_id or ''}-{team_id or ''}"
        if key in self.cached_bots:
            return self.cached_bots[key]
        bot = self.underlying.find_bot(
            enterprise_id=enterprise_id,
            team_id=team_id,
            is_enterprise_install=is_enterprise_install,
        )
        if bot:
            self.cached_bots[key] = bot
        return bot

    def find_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Installation]:
        if is_enterprise_install or team_id is None:
            team_id = ""
        key = f"{enterprise_id or ''}-{team_id or ''}-{user_id or ''}"
        if key in self.cached_installations:
            return self.cached_installations[key]
        installation = self.underlying.find_installation(
            enterprise_id=enterprise_id,
            team_id=team_id,
            user_id=user_id,
            is_enterprise_install=is_enterprise_install,
        )
        if installation:
            self.cached_installations[key] = installation
        return installation

    def delete_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
    ) -> None:
        self.underlying.delete_bot(
            enterprise_id=enterprise_id,
            team_id=team_id,
        )
        key = f"{enterprise_id or ''}-{team_id or ''}"
        if key in self.cached_bots:
            self.cached_bots.pop(key)

    def delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        self.underlying.delete_installation(
            enterprise_id=enterprise_id,
            team_id=team_id,
            user_id=user_id,
        )
        key_prefix = f"{enterprise_id or ''}-{team_id or ''}"
        for key in list(self.cached_installations.keys()):
            if key.startswith(key_prefix):
                self.cached_installations.pop(key)

    def delete_all(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
    ):
        self.underlying.delete_all(
            enterprise_id=enterprise_id,
            team_id=team_id,
        )
        key_prefix = f"{enterprise_id or ''}-{team_id or ''}"
        for key in list(self.cached_bots.keys()):
            if key.startswith(key_prefix):
                self.cached_bots.pop(key)
        for key in list(self.cached_installations.keys()):
            if key.startswith(key_prefix):
                self.cached_installations.pop(key)
