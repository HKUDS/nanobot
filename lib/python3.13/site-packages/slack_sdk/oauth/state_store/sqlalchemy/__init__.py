import logging
import time
from datetime import datetime, timezone
from logging import Logger
from uuid import uuid4

from ..state_store import OAuthStateStore
from ..async_state_store import AsyncOAuthStateStore
import sqlalchemy
from sqlalchemy import Table, Column, Integer, String, DateTime, and_, MetaData
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from slack_sdk.oauth.sqlalchemy_utils import normalize_datetime_for_db


class SQLAlchemyOAuthStateStore(OAuthStateStore):
    default_table_name: str = "slack_oauth_states"

    expiration_seconds: int
    engine: Engine
    metadata: MetaData
    oauth_states: Table

    @classmethod
    def build_oauth_states_table(cls, metadata: MetaData, table_name: str) -> Table:
        return sqlalchemy.Table(
            table_name,
            metadata,
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("state", String(200), nullable=False),
            Column("expire_at", DateTime, nullable=False),
        )

    def __init__(
        self,
        expiration_seconds: int,
        engine: Engine,
        logger: Logger = logging.getLogger(__name__),
        table_name: str = default_table_name,
    ):
        self.expiration_seconds = expiration_seconds
        self._logger = logger
        self.engine = engine
        self.metadata = MetaData()
        self.oauth_states = self.build_oauth_states_table(self.metadata, table_name)

    def create_tables(self):
        self.metadata.create_all(self.engine)

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = logging.getLogger(__name__)
        return self._logger

    def issue(self, *args, **kwargs) -> str:
        state: str = str(uuid4())
        now = normalize_datetime_for_db(datetime.fromtimestamp(time.time() + self.expiration_seconds, tz=timezone.utc))
        with self.engine.begin() as conn:
            conn.execute(
                self.oauth_states.insert(),
                {"state": state, "expire_at": now},
            )
        return state

    def consume(self, state: str) -> bool:
        try:
            now = normalize_datetime_for_db(datetime.now(tz=timezone.utc))
            with self.engine.begin() as conn:
                c = self.oauth_states.c
                query = self.oauth_states.select().where(and_(c.state == state, c.expire_at > now))
                result = conn.execute(query)
                for row in result.mappings():
                    self.logger.debug(f"consume's query result: {row}")
                    conn.execute(self.oauth_states.delete().where(c.id == row["id"]))
                    return True
            return False
        except Exception as e:
            message = f"Failed to find any persistent data for state: {state} - {e}"
            self.logger.warning(message)
            return False


class AsyncSQLAlchemyOAuthStateStore(AsyncOAuthStateStore):
    default_table_name: str = "slack_oauth_states"

    expiration_seconds: int
    engine: AsyncEngine
    metadata: MetaData
    oauth_states: Table

    @classmethod
    def build_oauth_states_table(cls, metadata: MetaData, table_name: str) -> Table:
        return sqlalchemy.Table(
            table_name,
            metadata,
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("state", String(200), nullable=False),
            Column("expire_at", DateTime, nullable=False),
        )

    def __init__(
        self,
        expiration_seconds: int,
        engine: AsyncEngine,
        logger: Logger = logging.getLogger(__name__),
        table_name: str = default_table_name,
    ):
        self.expiration_seconds = expiration_seconds
        self._logger = logger
        self.engine = engine
        self.metadata = MetaData()
        self.oauth_states = self.build_oauth_states_table(self.metadata, table_name)

    async def create_tables(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = logging.getLogger(__name__)
        return self._logger

    async def async_issue(self, *args, **kwargs) -> str:
        state: str = str(uuid4())
        now = normalize_datetime_for_db(datetime.fromtimestamp(time.time() + self.expiration_seconds, tz=timezone.utc))
        async with self.engine.begin() as conn:
            await conn.execute(
                self.oauth_states.insert(),
                {"state": state, "expire_at": now},
            )
        return state

    async def async_consume(self, state: str) -> bool:
        try:
            now = normalize_datetime_for_db(datetime.now(tz=timezone.utc))
            async with self.engine.begin() as conn:
                c = self.oauth_states.c
                query = self.oauth_states.select().where(and_(c.state == state, c.expire_at > now))
                result = await conn.execute(query)
                for row in result.mappings():
                    self.logger.debug(f"consume's query result: {row}")
                    await conn.execute(self.oauth_states.delete().where(c.id == row["id"]))
                    return True
            return False
        except Exception as e:
            message = f"Failed to find any persistent data for state: {state} - {e}"
            self.logger.warning(message)
            return False
