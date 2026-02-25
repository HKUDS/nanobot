from logging import Logger
from typing import Optional

from .models.bot import Bot
from .models.installation import Installation


class AsyncInstallationStore:
    """The installation store interface for asyncio-based apps.

    The minimum required methods are:

    * async_save(installation)
    * async_find_installation(enterprise_id, team_id, user_id, is_enterprise_install)

    If you would like to properly handle app uninstallations and token revocations,
    the following methods should be implemented.

    * async_delete_installation(enterprise_id, team_id, user_id)
    * async_delete_all(enterprise_id, team_id)

    If your app needs only bot scope installations, the simpler way to implement would be:

    * async_save(installation)
    * async_find_bot(enterprise_id, team_id, is_enterprise_install)
    * async_delete_bot(enterprise_id, team_id)
    * async_delete_all(enterprise_id, team_id)
    """

    @property
    def logger(self) -> Logger:
        raise NotImplementedError()

    async def async_save(self, installation: Installation):
        """Saves an installation data"""
        raise NotImplementedError()

    async def async_save_bot(self, bot: Bot):
        """Saves a bot installation data"""
        raise NotImplementedError()

    async def async_find_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Bot]:
        """Finds a bot scope installation per workspace / org"""
        raise NotImplementedError()

    async def async_find_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Installation]:
        """Finds a relevant installation for the given IDs.
        If the user_id is absent, this method may return the latest installation in the workspace / org.
        """
        raise NotImplementedError()

    async def async_delete_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
    ) -> None:
        """Deletes a bot scope installation per workspace / org"""
        raise NotImplementedError()

    async def async_delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        """Deletes an installation that matches the given IDs"""
        raise NotImplementedError()

    async def async_delete_all(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
    ):
        """Deletes all installation data for the given workspace / org"""
        await self.async_delete_bot(enterprise_id=enterprise_id, team_id=team_id)
        await self.async_delete_installation(enterprise_id=enterprise_id, team_id=team_id)
