import glob
import json
import logging
import os
from logging import Logger
from pathlib import Path
from typing import Optional, Union

from slack_sdk.oauth.installation_store.async_installation_store import (
    AsyncInstallationStore,
)
from slack_sdk.oauth.installation_store.installation_store import InstallationStore
from slack_sdk.oauth.installation_store.models.bot import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation


class FileInstallationStore(InstallationStore, AsyncInstallationStore):
    def __init__(
        self,
        *,
        base_dir: str = str(Path.home()) + "/.bolt-app-installation",
        historical_data_enabled: bool = True,
        client_id: Optional[str] = None,
        logger: Logger = logging.getLogger(__name__),
    ):
        self.base_dir = base_dir
        self.historical_data_enabled = historical_data_enabled
        self.client_id = client_id
        if self.client_id is not None:
            self.base_dir = f"{self.base_dir}/{self.client_id}"
        self._logger = logger

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = logging.getLogger(__name__)
        return self._logger

    async def async_save(self, installation: Installation):
        return self.save(installation)

    async def async_save_bot(self, bot: Bot):
        return self.save_bot(bot)

    def save(self, installation: Installation):
        none = "none"
        e_id = installation.enterprise_id or none
        t_id = installation.team_id or none
        team_installation_dir = f"{self.base_dir}/{e_id}-{t_id}"
        self._mkdir(team_installation_dir)

        self.save_bot(installation.to_bot())

        if self.historical_data_enabled:
            history_version: str = str(installation.installed_at)

            # per workspace
            entity: str = json.dumps(installation.__dict__)
            with open(f"{team_installation_dir}/installer-latest", "w") as f:
                f.write(entity)
            with open(f"{team_installation_dir}/installer-{history_version}", "w") as f:
                f.write(entity)

            # per workspace per user
            u_id = installation.user_id or none
            entity = json.dumps(installation.__dict__)
            with open(f"{team_installation_dir}/installer-{u_id}-latest", "w") as f:
                f.write(entity)
            with open(f"{team_installation_dir}/installer-{u_id}-{history_version}", "w") as f:
                f.write(entity)

        else:
            u_id = installation.user_id or none
            installer_filepath = f"{team_installation_dir}/installer-{u_id}-latest"
            with open(installer_filepath, "w") as f:
                entity = json.dumps(installation.__dict__)
                f.write(entity)

    def save_bot(self, bot: Bot):
        if bot.bot_token is None:
            self.logger.debug("Skipped saving a new row because of the absense of bot token in it")
            return

        none = "none"
        e_id = bot.enterprise_id or none
        t_id = bot.team_id or none
        team_installation_dir = f"{self.base_dir}/{e_id}-{t_id}"
        self._mkdir(team_installation_dir)

        if self.historical_data_enabled:
            history_version: str = str(bot.installed_at)

            entity: str = json.dumps(bot.__dict__)
            with open(f"{team_installation_dir}/bot-latest", "w") as f:
                f.write(entity)
            with open(f"{team_installation_dir}/bot-{history_version}", "w") as f:
                f.write(entity)
        else:
            with open(f"{team_installation_dir}/bot-latest", "w") as f:
                entity = json.dumps(bot.__dict__)
                f.write(entity)

    async def async_find_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Bot]:
        return self.find_bot(
            enterprise_id=enterprise_id,
            team_id=team_id,
            is_enterprise_install=is_enterprise_install,
        )

    def find_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Bot]:
        none = "none"
        e_id = enterprise_id or none
        t_id = team_id or none
        if is_enterprise_install:
            t_id = none
        bot_filepath = f"{self.base_dir}/{e_id}-{t_id}/bot-latest"
        try:
            with open(bot_filepath) as f:
                data = json.loads(f.read())
                return Bot(**data)
        except FileNotFoundError as e:
            message = f"Installation data missing for enterprise: {e_id}, team: {t_id}: {e}"
            self.logger.debug(message)
            return None

    async def async_find_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Installation]:
        return self.find_installation(
            enterprise_id=enterprise_id,
            team_id=team_id,
            user_id=user_id,
            is_enterprise_install=is_enterprise_install,
        )

    def find_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Installation]:
        none = "none"
        e_id = enterprise_id or none
        t_id = team_id or none
        if is_enterprise_install:
            t_id = none
        installation_filepath = f"{self.base_dir}/{e_id}-{t_id}/installer-latest"
        if user_id is not None:
            installation_filepath = f"{self.base_dir}/{e_id}-{t_id}/installer-{user_id}-latest"

        try:
            installation: Optional[Installation] = None
            with open(installation_filepath) as f:
                data = json.loads(f.read())
                installation = Installation(**data)

            has_user_installation = user_id is not None and installation is not None
            no_bot_token_installation = installation is not None and installation.bot_token is None
            should_find_bot_installation = has_user_installation or no_bot_token_installation
            if should_find_bot_installation:
                # Retrieve the latest bot token, just in case
                # See also: https://github.com/slackapi/bolt-python/issues/664
                latest_bot_installation = self.find_bot(
                    enterprise_id=enterprise_id,
                    team_id=team_id,
                    is_enterprise_install=is_enterprise_install,
                )
                if latest_bot_installation is not None and installation.bot_token != latest_bot_installation.bot_token:
                    # NOTE: this logic is based on the assumption that every single installation has bot scopes
                    # If you need to installation patterns without bot scopes in the same S3 bucket,
                    # please fork this code and implement your own logic.
                    installation.bot_id = latest_bot_installation.bot_id
                    installation.bot_user_id = latest_bot_installation.bot_user_id
                    installation.bot_token = latest_bot_installation.bot_token
                    installation.bot_scopes = latest_bot_installation.bot_scopes
                    installation.bot_refresh_token = latest_bot_installation.bot_refresh_token
                    installation.bot_token_expires_at = latest_bot_installation.bot_token_expires_at

            return installation

        except FileNotFoundError as e:
            message = f"Installation data missing for enterprise: {e_id}, team: {t_id}: {e}"
            self.logger.debug(message)
            return None

    async def async_delete_bot(self, *, enterprise_id: Optional[str], team_id: Optional[str]) -> None:
        return self.delete_bot(enterprise_id=enterprise_id, team_id=team_id)

    def delete_bot(self, *, enterprise_id: Optional[str], team_id: Optional[str]) -> None:
        none = "none"
        e_id = enterprise_id or none
        t_id = team_id or none
        filepath_glob = f"{self.base_dir}/{e_id}-{t_id}/bot-*"
        self._delete_by_glob(e_id, t_id, filepath_glob)

    async def async_delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        return self.delete_installation(enterprise_id=enterprise_id, team_id=team_id, user_id=user_id)

    def delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        none = "none"
        e_id = enterprise_id or none
        t_id = team_id or none
        if user_id is not None:
            filepath_glob = f"{self.base_dir}/{e_id}-{t_id}/installer-{user_id}-*"
        else:
            filepath_glob = f"{self.base_dir}/{e_id}-{t_id}/installer-*"
        self._delete_by_glob(e_id, t_id, filepath_glob)

    def _delete_by_glob(self, e_id: str, t_id: str, filepath_glob: str):
        for filepath in glob.glob(filepath_glob):
            try:
                os.remove(filepath)
            except FileNotFoundError as e:
                message = f"Failed to delete installation data for enterprise: {e_id}, team: {t_id}: {e}"
                self.logger.warning(message)

    @staticmethod
    def _mkdir(path: Union[str, Path]):
        if isinstance(path, str):
            path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
