import logging
from logging import Logger
from typing import Optional

import sqlalchemy
from sqlalchemy import (
    Table,
    Column,
    Integer,
    String,
    DateTime,
    Index,
    and_,
    desc,
    MetaData,
)
from sqlalchemy.engine import Engine
from sqlalchemy.sql.sqltypes import Boolean
from sqlalchemy.ext.asyncio import AsyncEngine
from slack_sdk.oauth.installation_store.installation_store import InstallationStore
from slack_sdk.oauth.installation_store.models.bot import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation
from slack_sdk.oauth.installation_store.async_installation_store import (
    AsyncInstallationStore,
)
from slack_sdk.oauth.sqlalchemy_utils import normalize_datetime_for_db


class SQLAlchemyInstallationStore(InstallationStore):
    default_bots_table_name: str = "slack_bots"
    default_installations_table_name: str = "slack_installations"

    client_id: str
    engine: Engine
    metadata: MetaData
    installations: Table

    @classmethod
    def build_installations_table(cls, metadata: MetaData, table_name: str) -> Table:
        return sqlalchemy.Table(
            table_name,
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("client_id", String(32), nullable=False),
            Column("app_id", String(32), nullable=False),
            Column("enterprise_id", String(32)),
            Column("enterprise_name", String(200)),
            Column("enterprise_url", String(200)),
            Column("team_id", String(32)),
            Column("team_name", String(200)),
            Column("bot_token", String(200)),
            Column("bot_id", String(32)),
            Column("bot_user_id", String(32)),
            Column("bot_scopes", String(1000)),
            Column("bot_refresh_token", String(200)),  # added in v3.8.0
            Column("bot_token_expires_at", DateTime),  # added in v3.8.0
            Column("user_id", String(32), nullable=False),
            Column("user_token", String(200)),
            Column("user_scopes", String(1000)),
            Column("user_refresh_token", String(200)),  # added in v3.8.0
            Column("user_token_expires_at", DateTime),  # added in v3.8.0
            Column("incoming_webhook_url", String(200)),
            Column("incoming_webhook_channel", String(200)),
            Column("incoming_webhook_channel_id", String(200)),
            Column("incoming_webhook_configuration_url", String(200)),
            Column("is_enterprise_install", Boolean, default=False, nullable=False),
            Column("token_type", String(32)),
            Column(
                "installed_at",
                DateTime,
                nullable=False,
                default=sqlalchemy.sql.func.now(),
            ),
            Index(
                f"{table_name}_idx",
                "client_id",
                "enterprise_id",
                "team_id",
                "user_id",
                "installed_at",
            ),
        )

    @classmethod
    def build_bots_table(cls, metadata: MetaData, table_name: str) -> Table:
        return Table(
            table_name,
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("client_id", String(32), nullable=False),
            Column("app_id", String(32), nullable=False),
            Column("enterprise_id", String(32)),
            Column("enterprise_name", String(200)),
            Column("team_id", String(32)),
            Column("team_name", String(200)),
            Column("bot_token", String(200)),
            Column("bot_id", String(32)),
            Column("bot_user_id", String(32)),
            Column("bot_scopes", String(1000)),
            Column("bot_refresh_token", String(200)),  # added in v3.8.0
            Column("bot_token_expires_at", DateTime),  # added in v3.8.0
            Column("is_enterprise_install", Boolean, default=False, nullable=False),
            Column(
                "installed_at",
                DateTime,
                nullable=False,
                default=sqlalchemy.sql.func.now(),
            ),
            Index(
                f"{table_name}_idx",
                "client_id",
                "enterprise_id",
                "team_id",
                "installed_at",
            ),
        )

    def __init__(
        self,
        client_id: str,
        engine: Engine,
        bots_table_name: str = default_bots_table_name,
        installations_table_name: str = default_installations_table_name,
        logger: Logger = logging.getLogger(__name__),
    ):
        self.metadata = sqlalchemy.MetaData()
        self.bots = self.build_bots_table(metadata=self.metadata, table_name=bots_table_name)
        self.installations = self.build_installations_table(metadata=self.metadata, table_name=installations_table_name)
        self.client_id = client_id
        self._logger = logger
        self.engine = engine

    def create_tables(self):
        self.metadata.create_all(self.engine)

    @property
    def logger(self) -> Logger:
        return self._logger

    def save(self, installation: Installation):
        with self.engine.begin() as conn:
            i = installation.to_dict()
            i["client_id"] = self.client_id
            i["installed_at"] = normalize_datetime_for_db(i.get("installed_at"))
            i["bot_token_expires_at"] = normalize_datetime_for_db(i.get("bot_token_expires_at"))
            i["user_token_expires_at"] = normalize_datetime_for_db(i.get("user_token_expires_at"))

            i_column = self.installations.c
            installations_rows = conn.execute(
                sqlalchemy.select(i_column.id)
                .where(
                    and_(
                        i_column.client_id == self.client_id,
                        i_column.enterprise_id == installation.enterprise_id,
                        i_column.team_id == installation.team_id,
                        i_column.installed_at == i.get("installed_at"),
                    )
                )
                .limit(1)
            )
            installations_row_id: Optional[str] = None
            for row in installations_rows.mappings():
                installations_row_id = row["id"]
            if installations_row_id is None:
                conn.execute(self.installations.insert(), i)
            else:
                update_statement = self.installations.update().where(i_column.id == installations_row_id).values(**i)
                conn.execute(update_statement, i)

        # bots
        self.save_bot(installation.to_bot())

    def save_bot(self, bot: Bot):
        with self.engine.begin() as conn:
            # bots
            b = bot.to_dict()
            b["client_id"] = self.client_id
            b["installed_at"] = normalize_datetime_for_db(b.get("installed_at"))
            b["bot_token_expires_at"] = normalize_datetime_for_db(b.get("bot_token_expires_at"))

            b_column = self.bots.c
            bots_rows = conn.execute(
                sqlalchemy.select(b_column.id)
                .where(
                    and_(
                        b_column.client_id == self.client_id,
                        b_column.enterprise_id == bot.enterprise_id,
                        b_column.team_id == bot.team_id,
                        b_column.installed_at == b.get("installed_at"),
                    )
                )
                .limit(1)
            )
            bots_row_id: Optional[str] = None
            for row in bots_rows.mappings():
                bots_row_id = row["id"]
            if bots_row_id is None:
                conn.execute(self.bots.insert(), b)
            else:
                update_statement = self.bots.update().where(b_column.id == bots_row_id).values(**b)
                conn.execute(update_statement, b)

    def find_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Bot]:
        if is_enterprise_install or team_id is None:
            team_id = None

        c = self.bots.c
        query = (
            self.bots.select()
            .where(
                and_(
                    c.client_id == self.client_id,
                    c.enterprise_id == enterprise_id,
                    c.team_id == team_id,
                    c.bot_token.is_not(None),  # the latest one that has a bot token
                )
            )
            .order_by(desc(c.installed_at))
            .limit(1)
        )

        with self.engine.connect() as conn:
            result: object = conn.execute(query)
            for row in result.mappings():  # type: ignore[attr-defined]
                return self.build_bot_entity(row)
            return None

    def find_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Installation]:
        if is_enterprise_install or team_id is None:
            team_id = None

        c = self.installations.c
        where_clause = and_(
            c.client_id == self.client_id,
            c.enterprise_id == enterprise_id,
            c.team_id == team_id,
        )
        if user_id is not None:
            where_clause = and_(
                c.client_id == self.client_id,
                c.enterprise_id == enterprise_id,
                c.team_id == team_id,
                c.user_id == user_id,
            )

        query = self.installations.select().where(where_clause).order_by(desc(c.installed_at)).limit(1)

        installation: Optional[Installation] = None
        with self.engine.connect() as conn:
            result: object = conn.execute(query)
            for row in result.mappings():  # type: ignore[attr-defined]
                installation = self.build_installation_entity(row)

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
            if (
                latest_bot_installation is not None
                and installation is not None
                and installation.bot_token != latest_bot_installation.bot_token
            ):
                installation.bot_id = latest_bot_installation.bot_id
                installation.bot_user_id = latest_bot_installation.bot_user_id
                installation.bot_token = latest_bot_installation.bot_token
                installation.bot_scopes = latest_bot_installation.bot_scopes
                installation.bot_refresh_token = latest_bot_installation.bot_refresh_token
                installation.bot_token_expires_at = latest_bot_installation.bot_token_expires_at

        return installation

    def delete_bot(self, *, enterprise_id: Optional[str], team_id: Optional[str]) -> None:
        table = self.bots
        c = table.c
        with self.engine.begin() as conn:
            deletion = table.delete().where(
                and_(
                    c.client_id == self.client_id,
                    c.enterprise_id == enterprise_id,
                    c.team_id == team_id,
                )
            )
            conn.execute(deletion)

    def delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        table = self.installations
        c = table.c
        with self.engine.begin() as conn:
            if user_id is not None:
                deletion = table.delete().where(
                    and_(
                        c.client_id == self.client_id,
                        c.enterprise_id == enterprise_id,
                        c.team_id == team_id,
                        c.user_id == user_id,
                    )
                )
                conn.execute(deletion)
            else:
                deletion = table.delete().where(
                    and_(
                        c.client_id == self.client_id,
                        c.enterprise_id == enterprise_id,
                        c.team_id == team_id,
                    )
                )
                conn.execute(deletion)

    @classmethod
    def build_installation_entity(cls, row) -> Installation:
        return Installation(
            app_id=row["app_id"],
            enterprise_id=row["enterprise_id"],
            enterprise_name=row["enterprise_name"],
            enterprise_url=row["enterprise_url"],
            team_id=row["team_id"],
            team_name=row["team_name"],
            bot_token=row["bot_token"],
            bot_id=row["bot_id"],
            bot_user_id=row["bot_user_id"],
            bot_scopes=row["bot_scopes"],
            bot_refresh_token=row["bot_refresh_token"],
            bot_token_expires_at=row["bot_token_expires_at"],
            user_id=row["user_id"],
            user_token=row["user_token"],
            user_scopes=row["user_scopes"],
            user_refresh_token=row["user_refresh_token"],
            user_token_expires_at=row["user_token_expires_at"],
            # Only the incoming webhook issued in the latest installation is set in this logic
            incoming_webhook_url=row["incoming_webhook_url"],
            incoming_webhook_channel=row["incoming_webhook_channel"],
            incoming_webhook_channel_id=row["incoming_webhook_channel_id"],
            incoming_webhook_configuration_url=row["incoming_webhook_configuration_url"],
            is_enterprise_install=row["is_enterprise_install"],
            token_type=row["token_type"],
            installed_at=row["installed_at"],
        )

    @classmethod
    def build_bot_entity(cls, row) -> Bot:
        return Bot(
            app_id=row["app_id"],
            enterprise_id=row["enterprise_id"],
            enterprise_name=row["enterprise_name"],
            team_id=row["team_id"],
            team_name=row["team_name"],
            bot_token=row["bot_token"],
            bot_id=row["bot_id"],
            bot_user_id=row["bot_user_id"],
            bot_scopes=row["bot_scopes"],
            bot_refresh_token=row["bot_refresh_token"],
            bot_token_expires_at=row["bot_token_expires_at"],
            is_enterprise_install=row["is_enterprise_install"],
            installed_at=row["installed_at"],
        )


class AsyncSQLAlchemyInstallationStore(AsyncInstallationStore):
    default_bots_table_name: str = "slack_bots"
    default_installations_table_name: str = "slack_installations"

    client_id: str
    engine: AsyncEngine
    metadata: MetaData
    installations: Table

    def __init__(
        self,
        client_id: str,
        engine: AsyncEngine,
        bots_table_name: str = default_bots_table_name,
        installations_table_name: str = default_installations_table_name,
        logger: Logger = logging.getLogger(__name__),
    ):
        self.metadata = sqlalchemy.MetaData()
        self.bots = self.build_bots_table(metadata=self.metadata, table_name=bots_table_name)
        self.installations = self.build_installations_table(metadata=self.metadata, table_name=installations_table_name)
        self.client_id = client_id
        self._logger = logger
        self.engine = engine

    @classmethod
    def build_installations_table(cls, metadata: MetaData, table_name: str) -> Table:
        return SQLAlchemyInstallationStore.build_installations_table(metadata, table_name)

    @classmethod
    def build_bots_table(cls, metadata: MetaData, table_name: str) -> Table:
        return SQLAlchemyInstallationStore.build_bots_table(metadata, table_name)

    async def create_tables(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    @property
    def logger(self) -> Logger:
        return self._logger

    async def async_save(self, installation: Installation):
        async with self.engine.begin() as conn:
            i = installation.to_dict()
            i["client_id"] = self.client_id
            i["installed_at"] = normalize_datetime_for_db(i.get("installed_at"))
            i["bot_token_expires_at"] = normalize_datetime_for_db(i.get("bot_token_expires_at"))
            i["user_token_expires_at"] = normalize_datetime_for_db(i.get("user_token_expires_at"))

            i_column = self.installations.c
            installations_rows = await conn.execute(
                sqlalchemy.select(i_column.id)
                .where(
                    and_(
                        i_column.client_id == self.client_id,
                        i_column.enterprise_id == installation.enterprise_id,
                        i_column.team_id == installation.team_id,
                        i_column.installed_at == i.get("installed_at"),
                    )
                )
                .limit(1)
            )
            installations_row_id: Optional[str] = None
            for row in installations_rows.mappings():
                installations_row_id = row["id"]
            if installations_row_id is None:
                await conn.execute(self.installations.insert(), i)
            else:
                update_statement = self.installations.update().where(i_column.id == installations_row_id).values(**i)
                await conn.execute(update_statement, i)

        # bots
        await self.async_save_bot(installation.to_bot())

    async def async_save_bot(self, bot: Bot):
        async with self.engine.begin() as conn:
            # bots
            b = bot.to_dict()
            b["client_id"] = self.client_id
            b["installed_at"] = normalize_datetime_for_db(b.get("installed_at"))
            b["bot_token_expires_at"] = normalize_datetime_for_db(b.get("bot_token_expires_at"))

            b_column = self.bots.c
            bots_rows = await conn.execute(
                sqlalchemy.select(b_column.id)
                .where(
                    and_(
                        b_column.client_id == self.client_id,
                        b_column.enterprise_id == bot.enterprise_id,
                        b_column.team_id == bot.team_id,
                        b_column.installed_at == b.get("installed_at"),
                    )
                )
                .limit(1)
            )
            bots_row_id: Optional[str] = None
            for row in bots_rows.mappings():
                bots_row_id = row["id"]
            if bots_row_id is None:
                await conn.execute(self.bots.insert(), b)
            else:
                update_statement = self.bots.update().where(b_column.id == bots_row_id).values(**b)
                await conn.execute(update_statement, b)

    async def async_find_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Bot]:
        if is_enterprise_install or team_id is None:
            team_id = None

        c = self.bots.c
        query = (
            self.bots.select()
            .where(
                and_(
                    c.client_id == self.client_id,
                    c.enterprise_id == enterprise_id,
                    c.team_id == team_id,
                    c.bot_token.is_not(None),  # the latest one that has a bot token
                )
            )
            .order_by(desc(c.installed_at))
            .limit(1)
        )

        async with self.engine.connect() as conn:
            result: object = await conn.execute(query)
            for row in result.mappings():  # type: ignore[attr-defined]
                return SQLAlchemyInstallationStore.build_bot_entity(row)
            return None

    async def async_find_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Installation]:
        if is_enterprise_install or team_id is None:
            team_id = None

        c = self.installations.c
        where_clause = and_(
            c.client_id == self.client_id,
            c.enterprise_id == enterprise_id,
            c.team_id == team_id,
        )
        if user_id is not None:
            where_clause = and_(
                c.client_id == self.client_id,
                c.enterprise_id == enterprise_id,
                c.team_id == team_id,
                c.user_id == user_id,
            )

        query = self.installations.select().where(where_clause).order_by(desc(c.installed_at)).limit(1)

        installation: Optional[Installation] = None
        async with self.engine.connect() as conn:
            result: object = await conn.execute(query)
            for row in result.mappings():  # type: ignore[attr-defined]
                installation = SQLAlchemyInstallationStore.build_installation_entity(row)

        has_user_installation = user_id is not None and installation is not None
        no_bot_token_installation = installation is not None and installation.bot_token is None
        should_find_bot_installation = has_user_installation or no_bot_token_installation
        if should_find_bot_installation:
            # Retrieve the latest bot token, just in case
            # See also: https://github.com/slackapi/bolt-python/issues/664
            latest_bot_installation = await self.async_find_bot(
                enterprise_id=enterprise_id,
                team_id=team_id,
                is_enterprise_install=is_enterprise_install,
            )
            if (
                latest_bot_installation is not None
                and installation is not None
                and installation.bot_token != latest_bot_installation.bot_token
            ):
                installation.bot_id = latest_bot_installation.bot_id
                installation.bot_user_id = latest_bot_installation.bot_user_id
                installation.bot_token = latest_bot_installation.bot_token
                installation.bot_scopes = latest_bot_installation.bot_scopes
                installation.bot_refresh_token = latest_bot_installation.bot_refresh_token
                installation.bot_token_expires_at = latest_bot_installation.bot_token_expires_at

        return installation

    async def async_delete_bot(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
    ) -> None:
        table = self.bots
        c = table.c
        async with self.engine.begin() as conn:
            deletion = table.delete().where(
                and_(
                    c.client_id == self.client_id,
                    c.enterprise_id == enterprise_id,
                    c.team_id == team_id,
                )
            )
            await conn.execute(deletion)

    async def async_delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        table = self.installations
        c = table.c
        async with self.engine.begin() as conn:
            if user_id is not None:
                deletion = table.delete().where(
                    and_(
                        c.client_id == self.client_id,
                        c.enterprise_id == enterprise_id,
                        c.team_id == team_id,
                        c.user_id == user_id,
                    )
                )
                await conn.execute(deletion)
            else:
                deletion = table.delete().where(
                    and_(
                        c.client_id == self.client_id,
                        c.enterprise_id == enterprise_id,
                        c.team_id == team_id,
                    )
                )
                await conn.execute(deletion)
