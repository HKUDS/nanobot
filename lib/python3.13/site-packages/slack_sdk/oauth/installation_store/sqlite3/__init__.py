import logging
import sqlite3
from logging import Logger
from sqlite3 import Connection
from typing import Optional

from slack_sdk.oauth.installation_store.async_installation_store import (
    AsyncInstallationStore,
)
from slack_sdk.oauth.installation_store.installation_store import InstallationStore
from slack_sdk.oauth.installation_store.models.bot import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation


class SQLite3InstallationStore(InstallationStore, AsyncInstallationStore):
    def __init__(
        self,
        *,
        database: str,
        client_id: str,
        logger: Logger = logging.getLogger(__name__),
    ):
        self.database = database
        self.client_id = client_id
        self.init_called = False
        self._logger = logger

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = logging.getLogger(__name__)
        return self._logger

    def init(self):
        try:
            with sqlite3.connect(database=self.database) as conn:
                cur = conn.execute("select count(1) from slack_installations;")
                row_num = cur.fetchone()[0]
                self.logger.debug(f"{row_num} installations are stored in {self.database}")
        except Exception:
            self.create_tables()
        self.init_called = True

    def connect(self) -> Connection:
        if not self.init_called:
            self.init()
        return sqlite3.connect(database=self.database)

    def create_tables(self):
        with sqlite3.connect(database=self.database) as conn:
            conn.execute(
                """
            create table slack_installations (
                id integer primary key autoincrement,
                client_id text not null,
                app_id text not null,
                enterprise_id text not null default '',
                enterprise_name text,
                enterprise_url text,
                team_id text not null default '',
                team_name text,
                bot_token text,
                bot_id text,
                bot_user_id text,
                bot_scopes text,
                bot_refresh_token text,  -- since v3.8
                bot_token_expires_at datetime,  -- since v3.8
                user_id text not null,
                user_token text,
                user_scopes text,
                user_refresh_token text,  -- since v3.8
                user_token_expires_at datetime,  -- since v3.8
                incoming_webhook_url text,
                incoming_webhook_channel text,
                incoming_webhook_channel_id text,
                incoming_webhook_configuration_url text,
                is_enterprise_install boolean not null default 0,
                token_type text,
                installed_at datetime not null default current_timestamp
            );
            """
            )
            conn.execute(
                """
            create index slack_installations_idx on slack_installations (
                client_id,
                enterprise_id,
                team_id,
                user_id,
                installed_at
            );
            """
            )
            conn.execute(
                """
            create table slack_bots (
                id integer primary key autoincrement,
                client_id text not null,
                app_id text not null,
                enterprise_id text not null default '',
                enterprise_name text,
                team_id text not null default '',
                team_name text,
                bot_token text not null,
                bot_id text not null,
                bot_user_id text not null,
                bot_scopes text,
                bot_refresh_token text,  -- since v3.8
                bot_token_expires_at datetime,  -- since v3.8
                is_enterprise_install boolean not null default 0,
                installed_at datetime not null default current_timestamp
            );
            """
            )
            conn.execute(
                """
            create index slack_bots_idx on slack_bots (
                client_id,
                enterprise_id,
                team_id,
                installed_at
            );
            """
            )
            self.logger.debug(f"Tables have been created (database: {self.database})")
            conn.commit()

    async def async_save(self, installation: Installation):
        return self.save(installation)

    async def async_save_bot(self, bot: Bot):
        return self.save_bot(bot)

    def save(self, installation: Installation):
        with self.connect() as conn:
            conn.execute(
                """
                insert into slack_installations (
                    client_id,
                    app_id,
                    enterprise_id,
                    enterprise_name,
                    enterprise_url,
                    team_id,
                    team_name,
                    bot_token,
                    bot_id,
                    bot_user_id,
                    bot_scopes,
                    bot_refresh_token,  -- since v3.8
                    bot_token_expires_at,  -- since v3.8
                    user_id,
                    user_token,
                    user_scopes,
                    user_refresh_token,  -- since v3.8
                    user_token_expires_at,  -- since v3.8
                    incoming_webhook_url,
                    incoming_webhook_channel,
                    incoming_webhook_channel_id,
                    incoming_webhook_configuration_url,
                    is_enterprise_install,
                    token_type
                )
                values
                (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?
                );
                """,
                [
                    self.client_id,
                    installation.app_id,
                    installation.enterprise_id or "",
                    installation.enterprise_name,
                    installation.enterprise_url,
                    installation.team_id or "",
                    installation.team_name,
                    installation.bot_token,
                    installation.bot_id,
                    installation.bot_user_id,
                    ",".join(installation.bot_scopes),  # type: ignore[arg-type]
                    installation.bot_refresh_token,
                    installation.bot_token_expires_at,
                    installation.user_id,
                    installation.user_token,
                    ",".join(installation.user_scopes) if installation.user_scopes else None,
                    installation.user_refresh_token,
                    installation.user_token_expires_at,
                    installation.incoming_webhook_url,
                    installation.incoming_webhook_channel,
                    installation.incoming_webhook_channel_id,
                    installation.incoming_webhook_configuration_url,
                    1 if installation.is_enterprise_install else 0,
                    installation.token_type,
                ],
            )
            self.logger.debug(
                f"New rows in slack_bots and slack_installations have been created (database: {self.database})"
            )
            conn.commit()

        self.save_bot(installation.to_bot())

    def save_bot(self, bot: Bot):
        if bot.bot_token is None:
            self.logger.debug("Skipped saving a new row because of the absense of bot token in it")
            return

        with self.connect() as conn:
            conn.execute(
                """
                insert into slack_bots (
                    client_id,
                    app_id,
                    enterprise_id,
                    enterprise_name,
                    team_id,
                    team_name,
                    bot_token,
                    bot_id,
                    bot_user_id,
                    bot_scopes,
                    bot_refresh_token,  -- since v3.8
                    bot_token_expires_at,  -- since v3.8
                    is_enterprise_install
                )
                values
                (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?
                );
                """,
                [
                    self.client_id,
                    bot.app_id,
                    bot.enterprise_id or "",
                    bot.enterprise_name,
                    bot.team_id or "",
                    bot.team_name,
                    bot.bot_token,
                    bot.bot_id,
                    bot.bot_user_id,
                    ",".join(bot.bot_scopes),
                    bot.bot_refresh_token,
                    bot.bot_token_expires_at,
                    bot.is_enterprise_install,
                ],
            )
            conn.commit()

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
        if is_enterprise_install or team_id is None:
            team_id = ""

        try:
            with self.connect() as conn:
                cur = conn.execute(
                    """
                    select
                        app_id,
                        enterprise_id,
                        enterprise_name,
                        team_id,
                        team_name,
                        bot_token,
                        bot_id,
                        bot_user_id,
                        bot_scopes,
                        bot_refresh_token,  -- since v3.8
                        bot_token_expires_at,  -- since v3.8
                        is_enterprise_install,
                        installed_at
                    from
                        slack_bots
                    where
                        client_id = ?
                        and
                        enterprise_id = ?
                        and
                        team_id = ?
                    order by installed_at desc
                    limit 1
                    """,
                    [self.client_id, enterprise_id or "", team_id or ""],
                )
                row = cur.fetchone()
                result = "found" if row and len(row) > 0 else "not found"
                self.logger.debug(f"find_bot's query result: {result} (database: {self.database})")
                if row and len(row) > 0:
                    bot = Bot(
                        app_id=row[0],
                        enterprise_id=row[1],
                        enterprise_name=row[2],
                        team_id=row[3],
                        team_name=row[4],
                        bot_token=row[5],
                        bot_id=row[6],
                        bot_user_id=row[7],
                        bot_scopes=row[8],
                        bot_refresh_token=row[9],
                        bot_token_expires_at=row[10],
                        is_enterprise_install=row[11],
                        installed_at=row[12],
                    )
                    return bot
                return None

        except Exception as e:
            message = f"Failed to find bot installation data for enterprise: {enterprise_id}, team: {team_id}: {e}"
            if self.logger.level <= logging.DEBUG:
                self.logger.exception(message)
            else:
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
        if is_enterprise_install or team_id is None:
            team_id = ""

        try:
            with self.connect() as conn:
                row = None
                columns = """
                    app_id,
                    enterprise_id,
                    enterprise_name,
                    enterprise_url,
                    team_id,
                    team_name,
                    bot_token,
                    bot_id,
                    bot_user_id,
                    bot_scopes,
                    bot_refresh_token,  -- since v3.8
                    bot_token_expires_at,  -- since v3.8
                    user_id,
                    user_token,
                    user_scopes,
                    user_refresh_token,  -- since v3.8
                    user_token_expires_at,  -- since v3.8
                    incoming_webhook_url,
                    incoming_webhook_channel,
                    incoming_webhook_channel_id,
                    incoming_webhook_configuration_url,
                    is_enterprise_install,
                    token_type,
                    installed_at
                """
                if user_id is None:
                    cur = conn.execute(
                        f"""
                        select
                            {columns}
                        from
                            slack_installations
                        where
                            client_id = ?
                            and
                            enterprise_id = ?
                            and
                            team_id = ?
                        order by installed_at desc
                        limit 1
                        """,
                        [self.client_id, enterprise_id or "", team_id],
                    )
                    row = cur.fetchone()
                else:
                    cur = conn.execute(
                        f"""
                        select
                            {columns}
                        from
                            slack_installations
                        where
                            client_id = ?
                            and
                            enterprise_id = ?
                            and
                            team_id = ?
                            and
                            user_id = ?
                        order by installed_at desc
                        limit 1
                        """,
                        [self.client_id, enterprise_id or "", team_id, user_id],
                    )
                    row = cur.fetchone()

                if row is None:
                    return None

                result = "found" if row and len(row) > 0 else "not found"
                self.logger.debug(f"find_installation's query result: {result} (database: {self.database})")
                if row and len(row) > 0:
                    installation = Installation(
                        app_id=row[0],
                        enterprise_id=row[1],
                        enterprise_name=row[2],
                        enterprise_url=row[3],
                        team_id=row[4],
                        team_name=row[5],
                        bot_token=row[6],
                        bot_id=row[7],
                        bot_user_id=row[8],
                        bot_scopes=row[9],
                        bot_refresh_token=row[10],
                        bot_token_expires_at=row[11],
                        user_id=row[12],
                        user_token=row[13],
                        user_scopes=row[14],
                        user_refresh_token=row[15],
                        user_token_expires_at=row[16],
                        incoming_webhook_url=row[17],
                        incoming_webhook_channel=row[18],
                        incoming_webhook_channel_id=row[19],
                        incoming_webhook_configuration_url=row[20],
                        is_enterprise_install=row[21],
                        token_type=row[22],
                        installed_at=row[23],
                    )

                    if user_id is not None:
                        # Retrieve the latest bot token, just in case
                        # See also: https://github.com/slackapi/bolt-python/issues/664
                        cur = conn.execute(
                            """
                            select
                                bot_token,
                                bot_id,
                                bot_user_id,
                                bot_scopes,
                                bot_refresh_token,
                                bot_token_expires_at
                            from
                                slack_installations
                            where
                                client_id = ?
                                and
                                enterprise_id = ?
                                and
                                team_id = ?
                                and
                                bot_token is not null
                            order by installed_at desc
                            limit 1
                            """,
                            [self.client_id, enterprise_id or "", team_id],
                        )
                        row = cur.fetchone()
                        installation.bot_token = row[0]
                        installation.bot_id = row[1]
                        installation.bot_user_id = row[2]
                        installation.bot_scopes = row[3]
                        installation.bot_refresh_token = row[4]
                        installation.bot_token_expires_at = row[5]

                    return installation
                return None

        except Exception as e:
            message = f"Failed to find an installation data for enterprise: {enterprise_id}, team: {team_id}: {e}"
            if self.logger.level <= logging.DEBUG:
                self.logger.exception(message)
            else:
                self.logger.warning(message)
            return None

    def delete_bot(self, *, enterprise_id: Optional[str], team_id: Optional[str]) -> None:
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    delete
                    from
                        slack_bots
                    where
                        client_id = ?
                        and
                        enterprise_id = ?
                        and
                        team_id = ?
                    """,
                    [self.client_id, enterprise_id or "", team_id or ""],
                )
                conn.commit()
        except Exception as e:
            message = f"Failed to delete bot installation data for enterprise: {enterprise_id}, team: {team_id}: {e}"
            if self.logger.level <= logging.DEBUG:
                self.logger.exception(message)
            else:
                self.logger.warning(message)

    def delete_installation(
        self,
        *,
        enterprise_id: Optional[str],
        team_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        try:
            with self.connect() as conn:
                if user_id is None:
                    conn.execute(
                        """
                        delete
                        from
                            slack_installations
                        where
                            client_id = ?
                            and
                            enterprise_id = ?
                            and
                            team_id = ?
                        """,
                        [self.client_id, enterprise_id or "", team_id],
                    )
                else:
                    conn.execute(
                        """
                        delete
                        from
                            slack_installations
                        where
                            client_id = ?
                            and
                            enterprise_id = ?
                            and
                            team_id = ?
                            and
                            user_id = ?
                        """,
                        [self.client_id, enterprise_id or "", team_id, user_id],
                    )
                conn.commit()
        except Exception as e:
            message = f"Failed to delete installation data for enterprise: {enterprise_id}, team: {team_id}: {e}"
            if self.logger.level <= logging.DEBUG:
                self.logger.exception(message)
            else:
                self.logger.warning(message)
