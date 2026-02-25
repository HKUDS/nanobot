import json
import logging
from logging import Logger
from typing import Optional

from botocore.client import BaseClient  # type: ignore[import-untyped]

from slack_sdk.errors import SlackClientConfigurationError
from slack_sdk.oauth.installation_store.async_installation_store import (
    AsyncInstallationStore,
)
from slack_sdk.oauth.installation_store.installation_store import InstallationStore
from slack_sdk.oauth.installation_store.models.bot import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation


class AmazonS3InstallationStore(InstallationStore, AsyncInstallationStore):
    def __init__(
        self,
        *,
        s3_client: BaseClient,
        bucket_name: str,
        client_id: str,
        historical_data_enabled: bool = True,
        logger: Logger = logging.getLogger(__name__),
    ):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.historical_data_enabled = historical_data_enabled
        self.client_id = client_id
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
        workspace_path = f"{self.client_id}/{e_id}-{t_id}"

        self.save_bot(installation.to_bot())

        if self.historical_data_enabled:
            history_version: str = str(installation.installed_at)

            # per workspace
            entity: str = json.dumps(installation.__dict__)
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Body=entity,
                Key=f"{workspace_path}/installer-latest",
            )
            self.logger.debug(f"S3 put_object response: {response}")
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Body=entity,
                Key=f"{workspace_path}/installer-{history_version}",
            )
            self.logger.debug(f"S3 put_object response: {response}")

            # per workspace per user
            u_id = installation.user_id or none
            entity = json.dumps(installation.__dict__)
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Body=entity,
                Key=f"{workspace_path}/installer-{u_id}-latest",
            )
            self.logger.debug(f"S3 put_object response: {response}")
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Body=entity,
                Key=f"{workspace_path}/installer-{u_id}-{history_version}",
            )
            self.logger.debug(f"S3 put_object response: {response}")

        else:
            # per workspace
            entity = json.dumps(installation.__dict__)
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Body=entity,
                Key=f"{workspace_path}/installer-latest",
            )
            self.logger.debug(f"S3 put_object response: {response}")

            # per workspace per user
            u_id = installation.user_id or none
            entity = json.dumps(installation.__dict__)
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Body=entity,
                Key=f"{workspace_path}/installer-{u_id}-latest",
            )
            self.logger.debug(f"S3 put_object response: {response}")

    def save_bot(self, bot: Bot):
        if bot.bot_token is None:
            self.logger.debug("Skipped saving a new row because of the absense of bot token in it")
            return

        none = "none"
        e_id = bot.enterprise_id or none
        t_id = bot.team_id or none
        workspace_path = f"{self.client_id}/{e_id}-{t_id}"

        if self.historical_data_enabled:
            history_version: str = str(bot.installed_at)
            entity: str = json.dumps(bot.__dict__)
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Body=entity,
                Key=f"{workspace_path}/bot-latest",
            )
            self.logger.debug(f"S3 put_object response: {response}")
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Body=entity,
                Key=f"{workspace_path}/bot-{history_version}",
            )
            self.logger.debug(f"S3 put_object response: {response}")

        else:
            entity = json.dumps(bot.__dict__)
            response = self.s3_client.put_object(
                Bucket=self.bucket_name,
                Body=entity,
                Key=f"{workspace_path}/bot-latest",
            )
            self.logger.debug(f"S3 put_object response: {response}")

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
        workspace_path = f"{self.client_id}/{e_id}-{t_id}"
        try:
            fetch_response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=f"{workspace_path}/bot-latest",
            )
            self.logger.debug(f"S3 get_object response: {fetch_response}")
            body = fetch_response["Body"].read().decode("utf-8")
            data = json.loads(body)
            return Bot(**data)
        except Exception as e:
            message = f"Failed to find bot installation data for enterprise: {e_id}, team: {t_id}: {e}"
            self.logger.warning(message)
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
        workspace_path = f"{self.client_id}/{e_id}-{t_id}"
        try:
            key = f"{workspace_path}/installer-{user_id}-latest" if user_id else f"{workspace_path}/installer-latest"
            fetch_response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=key,
            )
            self.logger.debug(f"S3 get_object response: {fetch_response}")
            body = fetch_response["Body"].read().decode("utf-8")
            data = json.loads(body)
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

        except Exception as e:
            message = f"Failed to find an installation data for enterprise: {e_id}, team: {t_id}: {e}"
            self.logger.warning(message)
            return None

    async def async_delete_bot(self, *, enterprise_id: Optional[str], team_id: Optional[str]) -> None:
        return self.delete_bot(
            enterprise_id=enterprise_id,
            team_id=team_id,
        )

    def delete_bot(self, *, enterprise_id: Optional[str], team_id: Optional[str]) -> None:
        none = "none"
        e_id = enterprise_id or none
        t_id = team_id or none
        workspace_path = f"{self.client_id}/{e_id}-{t_id}"
        objects = self.s3_client.list_objects(
            Bucket=self.bucket_name,
            Prefix=f"{workspace_path}/bot-",
        )
        for content in objects.get("Contents", []):
            key = content.get("Key")
            if key is not None:
                self.logger.info(f"Going to delete bot installation ({key})")
                try:
                    self.s3_client.delete_object(
                        Bucket=self.bucket_name,
                        Key=content.get("Key"),
                    )
                except Exception as e:
                    message = f"Failed to find bot installation data for enterprise: {e_id}, team: {t_id}: {e}"
                    raise SlackClientConfigurationError(message)

    async def async_delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        return self.delete_installation(
            enterprise_id=enterprise_id,
            team_id=team_id,
            user_id=user_id,
        )

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
        workspace_path = f"{self.client_id}/{e_id}-{t_id}"
        objects = self.s3_client.list_objects(
            Bucket=self.bucket_name,
            Prefix=f"{workspace_path}/installer-{user_id or ''}",
        )
        deleted_keys = []
        for content in objects.get("Contents", []):
            key = content.get("Key")
            if key is not None:
                self.logger.info(f"Going to delete installation ({key})")
                try:
                    self.s3_client.delete_object(
                        Bucket=self.bucket_name,
                        Key=key,
                    )
                    deleted_keys.append(key)
                except Exception as e:
                    message = f"Failed to find bot installation data for enterprise: {e_id}, team: {t_id}: {e}"
                    raise SlackClientConfigurationError(message)

                try:
                    no_user_id_key = key.replace(f"-{user_id}", "")
                    if not no_user_id_key.endswith("installer-latest"):
                        self.s3_client.delete_object(
                            Bucket=self.bucket_name,
                            Key=no_user_id_key,
                        )
                        deleted_keys.append(no_user_id_key)
                except Exception as e:
                    message = f"Failed to find bot installation data for enterprise: {e_id}, team: {t_id}: {e}"
                    raise SlackClientConfigurationError(message)

        # Check the remaining installation data
        objects = self.s3_client.list_objects(
            Bucket=self.bucket_name,
            Prefix=f"{workspace_path}/installer-",
            MaxKeys=10,  # the small number would be enough for this purpose
        )
        keys = [c.get("Key") for c in objects.get("Contents", []) if c.get("Key") not in deleted_keys]
        # If only installer-latest remains, we should delete the one as well
        if len(keys) == 1 and keys[0].endswith("installer-latest"):
            content = objects.get("Contents", [])[0]
            try:
                self.s3_client.delete_object(
                    Bucket=self.bucket_name,
                    Key=content.get("Key"),
                )
            except Exception as e:
                message = f"Failed to find bot installation data for enterprise: {e_id}, team: {t_id}: {e}"
                raise SlackClientConfigurationError(message)
