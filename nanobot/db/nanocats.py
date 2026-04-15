"""
NanoCats Database - SQLite for settings and state persistence
"""
import sqlite3
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nanocats.db")

DB_PATH = Path.home() / ".nanobot" / "nanocats.db"


def get_db() -> sqlite3.Connection:
    """Get database connection"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection):
    """Initialize database schema"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            color TEXT DEFAULT '#6b7280',
            is_hidden INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS agent_state (
            id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT,
            mood TEXT,
            current_task TEXT,
            project_id TEXT,
            last_activity TEXT,
            tokens_used TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()


class NanoCatsDB:
    """Database operations for NanoCats"""
    
    def __init__(self):
        self.conn = get_db()
        
    # Projects
    def get_projects(self, include_hidden: bool = False) -> list[dict]:
        """Get all projects"""
        query = "SELECT * FROM projects"
        if not include_hidden:
            query += " WHERE is_hidden = 0"
        query += " ORDER BY name"
        
        rows = self.conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    
    def save_project(self, project: dict):
        """Save or update project"""
        self.conn.execute("""
            INSERT INTO projects (id, name, path, color, is_hidden)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                path = excluded.path,
                color = excluded.color,
                is_hidden = excluded.is_hidden
        """, (
            project["id"],
            project["name"],
            project["path"],
            project.get("color", "#6b7280"),
            project.get("is_hidden", 0)
        ))
        self.conn.commit()
    
    def toggle_hidden(self, project_id: str, hidden: bool):
        """Toggle project hidden status"""
        self.conn.execute(
            "UPDATE projects SET is_hidden = ? WHERE id = ?",
            (1 if hidden else 0, project_id)
        )
        self.conn.commit()
    
    def scan_projects(self, base_path: str) -> list[dict]:
        """Scan projects directory and return all found projects"""
        base = Path(base_path)
        projects = []
        
        for item in base.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                projects.append({
                    "id": item.name,
                    "name": item.name,
                    "path": str(item),
                    "color": _get_project_color(item.name),
                    "is_hidden": 0
                })
        
        return projects
    
    # Settings
    def get_setting(self, key: str) -> Optional[str]:
        """Get a setting value"""
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
    
    def set_setting(self, key: str, value: str):
        """Set a setting value"""
        self.conn.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        self.conn.commit()
    
    # Agent state
    def save_agent(self, agent: dict):
        """Save agent state"""
        self.conn.execute("""
            INSERT INTO agent_state (id, name, status, mood, current_task, project_id, last_activity, tokens_used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                status = excluded.status,
                mood = excluded.mood,
                current_task = excluded.current_task,
                project_id = excluded.project_id,
                last_activity = excluded.last_activity,
                tokens_used = excluded.tokens_used
        """, (
            agent["id"],
            agent.get("name"),
            agent.get("status"),
            agent.get("mood"),
            agent.get("currentTask"),
            agent.get("projectId"),
            agent.get("lastActivity"),
            json.dumps(agent.get("tokensUsed"))
        ))
        self.conn.commit()
    
    def get_agents(self) -> list[dict]:
        """Get all saved agents"""
        rows = self.conn.execute("SELECT * FROM agent_state").fetchall()
        agents = []
        for row in rows:
            agent = dict(row)
            if agent.get("tokens_used"):
                agent["tokensUsed"] = json.loads(agent["tokens_used"])
            del agent["tokens_used"]
            del agent["updated_at"]
            agents.append(agent)
        return agents


def _get_project_color(name: str) -> str:
    """Generate color based on project name"""
    colors = [
        "#f472b6", "#ec4899", "#db2777",  # Pink
        "#a78bfa", "#8b5cf6", "#7c3aed",  # Purple
        "#60a5fa", "#3b82f6", "#2563eb",  # Blue
        "#34d399", "#10b981", "#059669",  # Green
        "#fbbf24", "#f59e0b", "#d97706",  # Yellow
        "#f87171", "#ef4444", "#dc2626",  # Red
        "#6ee7b7", "#34d399", "#10b981",  # Teal
        "#fcd34d", "#fbbf24", "#f59e0b",  # Amber
    ]
    # Simple hash
    hash_val = sum(ord(c) for c in name)
    return colors[hash_val % len(colors)]


# Global instance
_db: Optional[NanoCatsDB] = None

def get_nanocats_db() -> NanoCatsDB:
    global _db
    if _db is None:
        _db = NanoCatsDB()
    return _db
