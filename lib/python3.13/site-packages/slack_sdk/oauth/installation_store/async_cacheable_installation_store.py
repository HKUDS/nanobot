from logging import Logger
from typing import Optional, Dict

from slack_sdk.oauth.installation_store import Bot, Installation
from slack_sdk.oauth.installation_store.async_installation_store import (
    AsyncInstallationStore,
)


class AsyncCacheableInstallationStore(AsyncInstallationStore):
    underlying: AsyncInstallationStore
    cached_bots: Dict[str, Bot]
    cached_installations: Dict[str, Installation]

    def __init__(self, installation_store: AsyncInstallationStore):
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

    async def async_save(self, installation: Installation):
        # Invalidate cache data for update operations
        key = f"{installation.enterprise_id or ''}-{installation.team_id or ''}"
        if key in self.cached_bots:
            self.cached_bots.pop(key)
        key = f"{installation.enterprise_id or ''}-{installation.team_id or ''}-{installation.user_id or ''}"
        if key in self.cached_installations:
            self.cached_installations.pop(key)
        return await self.underlying.async_save(installation)

    async def async_save_bot(self, bot: Bot):
        # Invalidate cache data for update operations
        key = f"{bot.enterprise_id or ''}-{bot.team_id or ''}"
        if key in self.cached_bots:
            self.cached_bots.pop(key)
        return await self.underlying.async_save_bot(bot)

    async def async_find_bot(
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
        bot = await self.underlying.async_find_bot(
            enterprise_id=enterprise_id,
            team_id=team_id,
            is_enterprise_install=is_enterprise_install,
        )
        if bot:
            self.cached_bots[key] = bot
        return bot

    async def async_find_installation(
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
        installation = await self.underlying.async_find_installation(
            enterprise_id=enterprise_id,
            team_id=team_id,
            user_id=user_id,
            is_enterprise_install=is_enterprise_install,
        )
        if installation:
            self.cached_installations[key] = installation
        return installation

    async def async_delete_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
    ) -> None:
        await self.underlying.async_delete_bot(
            enterprise_id=enterprise_id,
            team_id=team_id,
        )
        key = f"{enterprise_id or ''}-{team_id or ''}"
        self.cached_bots.pop(key)

    async def async_delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        await self.underlying.async_delete_installation(
            enterprise_id=enterprise_id,
            team_id=team_id,
            user_id=user_id,
        )
        key_prefix = f"{enterprise_id or ''}-{team_id or ''}"
        for key in list(self.cached_installations.keys()):
            if key.startswith(key_prefix):
                self.cached_installations.pop(key)

    async def async_delete_all(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
    ):
        await self.underlying.async_delete_all(
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
