import logging
import sqlite3
import time
from logging import Logger
from sqlite3 import Connection
from uuid import uuid4

from ..async_state_store import AsyncOAuthStateStore
from ..state_store import OAuthStateStore


class SQLite3OAuthStateStore(OAuthStateStore, AsyncOAuthStateStore):
    def __init__(
        self,
        *,
        database: str,
        expiration_seconds: int,
        logger: Logger = logging.getLogger(__name__),
    ):
        self.database = database
        self.expiration_seconds = expiration_seconds
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
                cur = conn.execute("select count(1) from oauth_states;")
                row_num = cur.fetchone()[0]
                self.logger.debug(f"{row_num} oauth states are stored in {self.database}")
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
            create table oauth_states (
                id integer primary key autoincrement,
                state text not null,
                expire_at datetime not null
            );
            """
            )
            self.logger.debug(f"Tables have been created (database: {self.database})")
            conn.commit()

    async def async_issue(self, *args, **kwargs) -> str:
        return self.issue(*args, **kwargs)

    async def async_consume(self, state: str) -> bool:
        return self.consume(state)

    def issue(self, *args, **kwargs) -> str:
        state: str = str(uuid4())
        with self.connect() as conn:
            parameters = [
                state,
                time.time() + self.expiration_seconds,
            ]
            conn.execute("insert into oauth_states (state, expire_at) values (?, ?);", parameters)
            self.logger.debug(f"issue's insertion result: {parameters} (database: {self.database})")
            conn.commit()
        return state

    def consume(self, state: str) -> bool:
        try:
            with self.connect() as conn:
                cur = conn.execute(
                    "select id, state from oauth_states where state = ? and expire_at > ?;",
                    [state, time.time()],
                )
                row = cur.fetchone()
                self.logger.debug(f"consume's query result: {row} (database: {self.database})")
                if row and len(row) > 0:
                    id = row[0]
                    conn.execute("delete from oauth_states where id = ?;", [id])
                    conn.commit()
                    return True
            return False
        except Exception as e:
            message = f"Failed to find any persistent data for state: {state} - {e}"
            self.logger.warning(message)
            return False
