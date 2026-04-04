"""SQLite database layer for conversation and trajectory storage."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import aiosqlite

from config import DATABASE_PATH, DATA_DIR


def get_db_path() -> str:
    return str(DATABASE_PATH)


@contextmanager
def get_sync_connection():
    """Synchronous context manager for database connections."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_sync_db():
    """Initialize database schema synchronously."""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '新对话',
            model TEXT NOT NULL DEFAULT 'deepseek-chat',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            turn_id INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT '{}',
            action TEXT NOT NULL DEFAULT '',
            observation TEXT NOT NULL DEFAULT '',
            reward REAL NOT NULL DEFAULT 1.0,
            usage TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

    conn.commit()
    conn.close()


class Database:
    """Async database operations for Nanobot BFF."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or get_db_path()

    async def init(self):
        """Initialize database and create tables if needed."""
        DATA_DIR.mkdir(exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL DEFAULT '新对话',
                    model TEXT NOT NULL DEFAULT 'deepseek-chat',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    turn_id INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT '{}',
                    action TEXT NOT NULL DEFAULT '',
                    observation TEXT NOT NULL DEFAULT '',
                    reward REAL NOT NULL DEFAULT 1.0,
                    usage TEXT NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS branches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    branch_id TEXT NOT NULL,
                    branch_name TEXT NOT NULL DEFAULT 'main',
                    parent_branch_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    branch_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    s_t TEXT NOT NULL DEFAULT '{}',
                    a_t TEXT NOT NULL DEFAULT '{}',
                    o_t TEXT NOT NULL DEFAULT '{}',
                    r_t REAL NOT NULL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                )
            """)

            await db.commit()

    async def create_conversation(self, title: str, model: str) -> int:
        """Create a new conversation and return its ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO conversations (title, model) VALUES (?, ?)",
                (title, model)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_conversation(self, conversation_id: int) -> dict | None:
        """Get conversation by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_conversations(self) -> list[dict]:
        """List all conversations."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_conversation_time(self, conversation_id: int):
        """Update conversation's updated_at timestamp."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,)
            )
            await db.commit()

    async def add_turn(
        self,
        conversation_id: int,
        turn_id: int,
        state: dict[str, Any],
        action: str,
        observation: str,
        reward: float = 1.0,
        usage: dict[str, int] | None = None
    ) -> int:
        """Add a turn to a conversation and return the turn ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO turns
                   (conversation_id, turn_id, state, action, observation, reward, usage)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    turn_id,
                    json.dumps(state, ensure_ascii=False),
                    action,
                    observation,
                    reward,
                    json.dumps(usage or {}, ensure_ascii=False)
                )
            )
            await db.commit()
            await self.update_conversation_time(conversation_id)
            return cursor.lastrowid

    async def get_turns(self, conversation_id: int) -> list[dict]:
        """Get all turns for a conversation."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                """SELECT * FROM turns
                   WHERE conversation_id = ?
                   ORDER BY turn_id ASC""",
                (conversation_id,)
            )
            rows = await cursor.fetchall()
            turns = []
            for row in rows:
                turn = dict(row)
                turn["state"] = json.loads(turn["state"])
                turn["usage"] = json.loads(turn["usage"])
                turns.append(turn)
            return turns

    async def get_conversation_turn_count(self, conversation_id: int) -> int:
        """Get the number of turns in a conversation."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM turns WHERE conversation_id = ?",
                (conversation_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def create_branch(
        self,
        conversation_id: int,
        branch_id: str,
        branch_name: str = "main",
        parent_branch_id: str | None = None
    ) -> int:
        """Create a new branch for a conversation."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO branches (conversation_id, branch_id, branch_name, parent_branch_id)
                   VALUES (?, ?, ?, ?)""",
                (conversation_id, branch_id, branch_name, parent_branch_id)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_branches(self, conversation_id: int) -> list[dict]:
        """Get all branches for a conversation."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                "SELECT * FROM branches WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def save_trace(
        self,
        conversation_id: int,
        branch_id: str,
        iteration: int,
        s_t: dict[str, Any],
        a_t: dict[str, Any],
        o_t: dict[str, Any],
        r_t: float
    ) -> int:
        """Save a complete (s,a,o,r) trajectory tuple."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO traces
                   (conversation_id, branch_id, iteration, s_t, a_t, o_t, r_t)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    branch_id,
                    iteration,
                    json.dumps(s_t, ensure_ascii=False),
                    json.dumps(a_t, ensure_ascii=False),
                    json.dumps(o_t, ensure_ascii=False),
                    r_t
                )
            )
            await db.commit()
            return cursor.lastrowid

    async def get_traces(self, conversation_id: int, branch_id: str | None = None) -> list[dict]:
        """Get all traces for a conversation, optionally filtered by branch."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            if branch_id:
                cursor = await db.execute(
                    """SELECT * FROM traces
                       WHERE conversation_id = ? AND branch_id = ?
                       ORDER BY iteration ASC""",
                    (conversation_id, branch_id)
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM traces
                       WHERE conversation_id = ?
                       ORDER BY branch_id, iteration ASC""",
                    (conversation_id,)
                )
            rows = await cursor.fetchall()
            traces = []
            for row in rows:
                trace = dict(row)
                trace["s_t"] = json.loads(trace["s_t"])
                trace["a_t"] = json.loads(trace["a_t"])
                trace["o_t"] = json.loads(trace["o_t"])
                traces.append(trace)
            return traces
