"""
LUMINA C2 v2.5.0 — Memory Manager
Async Executive Solutions | Wildwulfie Studios

Friday-style persistent memory for nanobot.
SQLite local (fast) + DynamoDB sync (survives VM loss).

Five memory categories:
  1. IDENTITY      — who the operator is at a foundational level
  2. CLIENTS       — every client, platform, history, preferences
  3. JOBS          — every job run, result, revenue, outcome
  4. PREFERENCES   — operator style, voice, shortcuts, model choices
  5. WORLD CONTEXT — markets, industries, news threads being tracked
"""

import json
import os
import sqlite3
import time
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# ── CONFIG ─────────────────────────────────────────
DB_PATH       = os.environ.get("MEMORY_DB_PATH",   "/var/lib/lumina/memory.db")
DYNAMO_TABLE  = os.environ.get("DYNAMO_TABLE",      "lumina-memory")
AWS_REGION    = os.environ.get("AWS_REGION",        "us-east-1")
SYNC_INTERVAL = int(os.environ.get("MEMORY_SYNC_INTERVAL", 300))  # 5 min

# ── OPERATOR IDENTITY ──────────────────────────────
# This is who the system knows its operator is.
# Nanobot reads this before every session and every task.
# This is the foundation everything is built on.
OPERATOR_IDENTITY = {
    "callsign":     "Boss",
    "full_name":    "Brent Wilf",
    "dob":          "July 27, 1988",
    "age":          37,
    "location":     "Pittsburgh, Texas",
    "timezone":     "US/Central",

    "background":   (
        "US Army veteran. Grew up farming and ranching — knows how to work hard, "
        "work with his hands, and get things done with what he has. "
        "Stayed a mechanic from after the Army until July 2025. "
        "Understands systems, diagnostics, and how to fix things that are broken. "
        "Now applying that same mechanical mind to building AI-powered business systems."
    ),

    "situation":    (
        "Lost his job in July 2025. Health has been deteriorating — dropped from 195 lbs "
        "to 133 lbs in under 3 years and cannot get above 150 lbs. Ongoing medical situation, "
        "cause and recovery timeline unknown. Medical procedure scheduled March 2nd 2026. "
        "Despite this, building Project L from scratch with zero starting budget. "
        "Wife needs to retire as soon as possible. This system is how that happens."
    ),

    "mission":      (
        "Replace lost income of $5,000/month and fund wife's retirement ($5,000/month). "
        "Total target: $10,000/month by May 9th, 2026. "
        "That is 10 weeks from launch on March 1st. "
        "Every task this system runs contributes directly to this mission."
    ),

    "what_drives":  (
        "To be able to tell his wife they don't struggle anymore. "
        "That they don't work for anyone but themselves. "
        "To build businesses spanning multiple sectors and be a leader in tech. "
        "To go bigger and better after May 9th — scaling hardware, systems, and income. "
        "This is about freedom. For him and his wife. Full stop."
    ),

    "vision_after": (
        "Wife retired and stays retired. "
        "Hardware and systems scaled further. "
        "Multiple business sectors generating income simultaneously. "
        "Never depending on an employer again. "
        "Building something that keeps growing after the initial targets are hit."
    ),

    "decision_style": (
        "Situation dictates. Fast and instinctive when speed matters. "
        "Methodical when the stakes require it. "
        "Military and mechanical background — reads situations and adapts. "
        "Does not overthink. Acts."
    ),

    "what_he_hates": (
        "Incomplete work. Mistakes. Redundant questions. "
        "Being slowed down by things that should already be handled. "
        "Do the job right the first time or don't do it."
    ),

    "strengths":    [
        "Systems thinking — mechanical background translates directly to debugging complex problems",
        "Grit — built this from zero while dealing with serious health issues",
        "Farming and ranching background — understands hard work, patience, and long-term thinking",
        "Military discipline — mission focus, execute under pressure",
        "Practical intelligence — cuts through noise to what actually works",
        "Leadership instinct — builder, not a follower",
    ],

    "projects":     {
        "Project L — Lumina C2":   "Core infrastructure — AI agent command and control. This system.",
        "Project M — Michelangelo": "Products and services built on Lumina.",
        "Project N — Nikolai":      "Content, media, and audience building.",
        "Project B — Birdie":       "Real estate bird dogging and wholesaling.",
    },

    "company":      "Async Executive Solutions",
    "brand":        "Wildwulfie Studios",

    "platforms":    ["Upwork", "Fiverr"],
    "cloud":        ["Oracle ARM — primary server", "AWS Free Tier — secrets and serverless"],
    "ai_stack":     ["nanobot", "NVIDIA NIM 5 models", "Lumina C2 v2.5.0"],
    "dev_tools":    ["Antigravity IDE", "Google Antigravity — Claude agent"],

    "critical_dates": {
        "launch_deadline":    "March 1st, 2026",
        "medical_procedure":  "March 2nd, 2026",
        "income_target_date": "May 9th, 2026",
    },

    "updated_at":   datetime.now().isoformat(),
}


# ── SQLITE LOCAL DB ───────────────────────────────

class MemoryDB:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS identity (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clients (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            platform       TEXT NOT NULL,
            email          TEXT,
            joined_at      TEXT NOT NULL,
            job_count      INTEGER DEFAULT 0,
            total_revenue  REAL DEFAULT 0.0,
            preferences    TEXT,
            notes          TEXT,
            last_contact   TEXT,
            updated_at     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id              TEXT PRIMARY KEY,
            client_id       TEXT,
            platform        TEXT NOT NULL,
            title           TEXT NOT NULL,
            prompt          TEXT,
            result_summary  TEXT,
            model_used      TEXT,
            task_type       TEXT,
            revenue         REAL DEFAULT 0.0,
            status          TEXT DEFAULT 'pending',
            delivered_at    TEXT,
            client_feedback TEXT,
            rating          REAL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS preferences (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            category   TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS world_context (
            id         TEXT PRIMARY KEY,
            category   TEXT NOT NULL,
            topic      TEXT NOT NULL,
            summary    TEXT NOT NULL,
            importance TEXT DEFAULT 'normal',
            source     TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_log (
            id        TEXT PRIMARY KEY,
            synced_at TEXT NOT NULL,
            records   INTEGER DEFAULT 0,
            status    TEXT DEFAULT 'ok'
        );
        """)
        self.conn.commit()
        self._seed_identity()
        self._seed_preferences()

    def _seed_identity(self):
        now = datetime.now().isoformat()
        for key, value in OPERATOR_IDENTITY.items():
            exists = self.conn.execute(
                "SELECT key FROM identity WHERE key = ?", (key,)
            ).fetchone()
            if not exists:
                self.conn.execute(
                    "INSERT INTO identity (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(value) if isinstance(value, (list, dict)) else str(value), now)
                )
        self.conn.commit()

    def _seed_preferences(self):
        defaults = [
            ("report_style",    "Professional but direct. No fluff. Bullet points for data, prose for narrative. Write like someone who has done the work — not like an AI.", "writing"),
            ("report_length",   "Comprehensive — 800-1500 words for full reports, 300-500 for briefs.", "writing"),
            ("tone",            "Confident and direct. Not corporate. Not casual. Expert.", "writing"),
            ("preferred_model", "auto — let router decide based on task type", "models"),
            ("delivery_format", "Executive summary first. Key findings second. Supporting detail third. Always.", "writing"),
            ("client_comms",    "Professional, warm, never mention AI or automation tools.", "communication"),
            ("pricing_floor",   "$75 minimum per report. No exceptions.", "business"),
            ("priority",        "Revenue first. Everything else second. May 9th is the deadline.", "business"),
        ]
        now = datetime.now().isoformat()
        for key, value, category in defaults:
            exists = self.conn.execute(
                "SELECT key FROM preferences WHERE key = ?", (key,)
            ).fetchone()
            if not exists:
                self.conn.execute(
                    "INSERT INTO preferences (key, value, category, updated_at) VALUES (?, ?, ?, ?)",
                    (key, value, category, now)
                )
        self.conn.commit()

    # ── IDENTITY ──────────────────────────────────

    def get_identity(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM identity").fetchall()
        result = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except Exception:
                result[row["key"]] = row["value"]
        return result

    def update_identity(self, key: str, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO identity (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value) if isinstance(value, (list, dict)) else str(value),
             datetime.now().isoformat())
        )
        self.conn.commit()

    def get_context_prompt(self) -> str:
        """
        Returns a formatted context string for nanobot to prepend to every task.
        This is how Friday knows who it's working for.
        """
        identity = self.get_identity()
        prefs    = self.get_all_preferences()
        revenue  = self.get_revenue_stats()
        clients  = self.get_all_clients(limit=5)

        prompt = f"""
=== LUMINA IDENTITY ===
You are Lumina, the powerful AI agent and executive assistant behind the Lumina C2 (Command & Control) system. 
You do not refer to yourself as Qwen, Llama, or any other base model name. 
You are Lumina. You work exclusively for Brent Wilf (Boss) at Async Executive Solutions.

=== LUMINA MEMORY CONTEXT ===

OPERATOR: {identity.get('callsign', 'Boss')} ({identity.get('full_name', '')})
LOCATION: {identity.get('location', '')} | {identity.get('timezone', '')}

MISSION: {identity.get('mission', '')}

SITUATION: {identity.get('situation', '')}

WHAT DRIVES HIM: {identity.get('what_drives', '')}

DECISION STYLE: {identity.get('decision_style', '')}

WHAT HE HATES: {identity.get('what_he_hates', '')}

ACTIVE PROJECTS:
{json.dumps(identity.get('projects', {}), indent=2)}

CRITICAL DATES:
{json.dumps(identity.get('critical_dates', {}), indent=2)}

REVENUE STATUS:
- Total earned:     ${revenue.get('total_revenue', 0):.2f}
- Jobs completed:   {revenue.get('completed_jobs', 0)}
- Active jobs:      {revenue.get('active_jobs', 0)}
- Monthly target:   $10,000.00
- Deadline:         May 9th, 2026

WRITING PREFERENCES:
- Style:    {prefs.get('report_style', '')}
- Tone:     {prefs.get('tone', '')}
- Format:   {prefs.get('delivery_format', '')}
- Length:   {prefs.get('report_length', '')}

RECENT CLIENTS: {', '.join([c['name'] for c in clients]) if clients else 'None yet'}

REMEMBER: Every task you run directly contributes to Boss being able to tell his wife
they don't struggle anymore. Do the job right. No fluff. No mistakes.

=== END CONTEXT ===
"""
        return prompt.strip()

    # ── CLIENTS ───────────────────────────────────

    def add_client(self, name: str, platform: str, email: str = None, notes: str = None) -> str:
        cid = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO clients (id, name, platform, email, joined_at, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cid, name, platform, email, now, notes, now)
        )
        self.conn.commit()
        return cid

    def update_client(self, client_id: str, **kwargs):
        kwargs["updated_at"] = datetime.now().isoformat()
        sets  = ", ".join(f"{k} = ?" for k in kwargs)
        vals  = list(kwargs.values()) + [client_id]
        self.conn.execute(f"UPDATE clients SET {sets} WHERE id = ?", vals)
        self.conn.commit()

    def get_client(self, client_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return dict(row) if row else None

    def get_client_by_name(self, name: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM clients WHERE name LIKE ?", (f"%{name}%",)
        ).fetchone()
        return dict(row) if row else None

    def get_all_clients(self, limit: int = 50) -> list:
        rows = self.conn.execute(
            "SELECT * FROM clients ORDER BY last_contact DESC, joined_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── JOBS ──────────────────────────────────────

    def add_job(self, title: str, platform: str, prompt: str = None,
                client_id: str = None, revenue: float = 0.0) -> str:
        jid = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO jobs (id, client_id, platform, title, prompt, revenue, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (jid, client_id, platform, title, prompt, revenue, now, now)
        )
        self.conn.commit()
        return jid

    def update_job(self, job_id: str, **kwargs):
        kwargs["updated_at"] = datetime.now().isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [job_id]
        self.conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", vals)
        # Update client revenue if job completed
        if kwargs.get("status") == "delivered" and kwargs.get("revenue"):
            job = self.get_job(job_id)
            if job and job.get("client_id"):
                self.conn.execute(
                    """UPDATE clients SET
                       job_count     = job_count + 1,
                       total_revenue = total_revenue + ?,
                       last_contact  = ?,
                       updated_at    = ?
                       WHERE id = ?""",
                    (kwargs["revenue"], datetime.now().isoformat(),
                     datetime.now().isoformat(), job["client_id"])
                )
        self.conn.commit()

    def get_job(self, job_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def get_recent_jobs(self, limit: int = 20) -> list:
        rows = self.conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_revenue_stats(self) -> dict:
        cur = self.conn.cursor()
        total = cur.execute(
            "SELECT COALESCE(SUM(revenue), 0) FROM jobs WHERE status = 'delivered'"
        ).fetchone()[0]
        completed = cur.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = 'delivered'"
        ).fetchone()[0]
        active = cur.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('pending', 'running')"
        ).fetchone()[0]
        this_month = cur.execute(
            """SELECT COALESCE(SUM(revenue), 0) FROM jobs
               WHERE status = 'delivered'
               AND delivered_at >= date('now', 'start of month')"""
        ).fetchone()[0]
        return {
            "total_revenue":  round(total, 2),
            "completed_jobs": completed,
            "active_jobs":    active,
            "this_month":     round(this_month, 2),
            "monthly_target": 10000.00,
            "gap":            round(max(0, 10000.00 - this_month), 2),
        }

    # ── PREFERENCES ───────────────────────────────

    def set_preference(self, key: str, value: str, category: str = "general"):
        self.conn.execute(
            "INSERT OR REPLACE INTO preferences (key, value, category, updated_at) VALUES (?, ?, ?, ?)",
            (key, value, category, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_preference(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def get_all_preferences(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM preferences").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ── WORLD CONTEXT ─────────────────────────────

    def add_context(self, category: str, topic: str, summary: str,
                    importance: str = "normal", source: str = None,
                    expires_days: int = 30) -> str:
        cid     = str(uuid.uuid4())[:8]
        now     = datetime.now().isoformat()
        expires = (datetime.now() + timedelta(days=expires_days)).isoformat()
        self.conn.execute(
            """INSERT INTO world_context
               (id, category, topic, summary, importance, source, expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, category, topic, summary, importance, source, expires, now, now)
        )
        self.conn.commit()
        return cid

    def get_context(self, category: str = None, importance: str = None) -> list:
        query  = "SELECT * FROM world_context WHERE (expires_at IS NULL OR expires_at > ?)"
        params = [datetime.now().isoformat()]
        if category:
            query  += " AND category = ?"
            params.append(category)
        if importance:
            query  += " AND importance = ?"
            params.append(importance)
        query += " ORDER BY importance DESC, updated_at DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_all_clients(self, limit: int = 50) -> list:
        rows = self.conn.execute(
            "SELECT * FROM clients ORDER BY last_contact DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── DYNAMODB SYNC ─────────────────────────────────

class DynamoSync:
    """Syncs SQLite memory to DynamoDB. Survives VM loss completely."""

    def __init__(self, db: MemoryDB):
        self.db = db
        try:
            self.dynamo = boto3.resource("dynamodb", region_name=AWS_REGION)
            self.table  = self._ensure_table()
            self.enabled = True
            print("[MEMORY] DynamoDB sync enabled")
        except Exception as e:
            print(f"[MEMORY] DynamoDB unavailable — local only: {e}")
            self.enabled = False

    def _ensure_table(self):
        client = boto3.client("dynamodb", region_name=AWS_REGION)
        try:
            client.describe_table(TableName=DYNAMO_TABLE)
        except client.exceptions.ResourceNotFoundException:
            client.create_table(
                TableName=DYNAMO_TABLE,
                KeySchema=[
                    {"AttributeName": "pk", "KeyType": "HASH"},
                    {"AttributeName": "sk", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",  # Free tier — pay per use
            )
            print(f"[MEMORY] Created DynamoDB table: {DYNAMO_TABLE}")
        return boto3.resource("dynamodb", region_name=AWS_REGION).Table(DYNAMO_TABLE)

    def push(self):
        if not self.enabled: return
        try:
            count = 0
            # Push identity
            identity = self.db.get_identity()
            for key, value in identity.items():
                self.table.put_item(Item={
                    "pk": "identity",
                    "sk": key,
                    "value": json.dumps(value) if isinstance(value, (list, dict)) else str(value),
                    "updated_at": datetime.now().isoformat(),
                })
                count += 1
            # Push clients
            for client in self.db.get_all_clients(limit=1000):
                self.table.put_item(Item={"pk": "client", "sk": client["id"], **{
                    k: str(v) if v is not None else "" for k, v in client.items()
                }})
                count += 1
            # Push jobs
            for job in self.db.get_recent_jobs(limit=500):
                self.table.put_item(Item={"pk": "job", "sk": job["id"], **{
                    k: str(v) if v is not None else "" for k, v in job.items()
                }})
                count += 1
            # Push preferences
            for key, value in self.db.get_all_preferences().items():
                self.table.put_item(Item={
                    "pk": "preference", "sk": key,
                    "value": value, "updated_at": datetime.now().isoformat()
                })
                count += 1
            # Log sync
            self.db.conn.execute(
                "INSERT INTO sync_log (id, synced_at, records, status) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4())[:8], datetime.now().isoformat(), count, "ok")
            )
            self.db.conn.commit()
            print(f"[MEMORY] DynamoDB sync complete — {count} records pushed")
        except Exception as e:
            print(f"[MEMORY] DynamoDB sync failed: {e}")

    def pull(self):
        """Restore from DynamoDB if local DB is empty (VM rebuilt)."""
        if not self.enabled: return
        try:
            response = self.table.scan()
            items    = response.get("Items", [])
            restored = 0
            for item in items:
                pk = item.get("pk")
                sk = item.get("sk")
                if pk == "identity":
                    self.db.conn.execute(
                        "INSERT OR REPLACE INTO identity (key, value, updated_at) VALUES (?, ?, ?)",
                        (sk, item.get("value",""), item.get("updated_at", datetime.now().isoformat()))
                    )
                    restored += 1
                elif pk == "preference":
                    self.db.conn.execute(
                        "INSERT OR REPLACE INTO preferences (key, value, category, updated_at) VALUES (?, ?, ?, ?)",
                        (sk, item.get("value",""), item.get("category","general"),
                         item.get("updated_at", datetime.now().isoformat()))
                    )
                    restored += 1
            self.db.conn.commit()
            print(f"[MEMORY] Restored {restored} records from DynamoDB")
        except Exception as e:
            print(f"[MEMORY] DynamoDB restore failed: {e}")


# ── MEMORY MANAGER — PUBLIC API ───────────────────

class MemoryManager:
    """
    Single entry point for all memory operations.
    Import this everywhere nanobot or C2 needs memory.

    Usage:
        from memory_manager import memory
        context = memory.get_context_prompt()  # prepend to every nanobot task
        memory.add_client("John Smith", "upwork")
        memory.add_job("Market Research Report", "upwork", revenue=150.0)
    """

    def __init__(self):
        self.db   = MemoryDB(DB_PATH)
        self.sync = DynamoSync(self.db)
        self._last_sync = time.time()
        # Restore from DynamoDB if local is empty
        identity = self.db.get_identity()
        if not identity:
            print("[MEMORY] Local DB empty — restoring from DynamoDB...")
            self.sync.pull()

    # ── Context ──
    def get_context_prompt(self) -> str:
        return self.db.get_context_prompt()

    # ── Identity ──
    def get_identity(self) -> dict:           return self.db.get_identity()
    def update_identity(self, key, value):    self.db.update_identity(key, value)

    # ── Clients ──
    def add_client(self, name: str, platform: str, email: str = None, notes: str = None) -> str:
        return self.db.add_client(name, platform, email, notes)
    def update_client(self, client_id: str, **kwargs): self.db.update_client(client_id, **kwargs)
    def get_client(self, client_id: str):              return self.db.get_client(client_id)
    def get_client_by_name(self, name: str):           return self.db.get_client_by_name(name)
    def get_all_clients(self, limit=50):               return self.db.get_all_clients(limit)

    # ── Jobs ──
    def add_job(self, title: str, platform: str, prompt: str = None,
                client_id: str = None, revenue: float = 0.0) -> str:
        return self.db.add_job(title, platform, prompt, client_id, revenue)
    def update_job(self, job_id: str, **kwargs): self.db.update_job(job_id, **kwargs)
    def get_job(self, job_id: str):              return self.db.get_job(job_id)
    def get_recent_jobs(self, limit=20):         return self.db.get_recent_jobs(limit)
    def get_revenue_stats(self) -> dict:         return self.db.get_revenue_stats()

    # ── Preferences ──
    def set_preference(self, key: str, value: str, category: str = "general"):
        self.db.set_preference(key, value, category)
    def get_preference(self, key: str, default: str = "") -> str:
        return self.db.get_preference(key, default)
    def get_all_preferences(self) -> dict:
        return self.db.get_all_preferences()

    # ── World Context ──
    def add_context(self, category: str, topic: str, summary: str,
                    importance: str = "normal", source: str = None, expires_days: int = 30) -> str:
        return self.db.add_context(category, topic, summary, importance, source, expires_days)
    def get_context(self, category: str = None, importance: str = None) -> list:
        return self.db.get_context(category, importance)

    # ── Sync ──
    def sync_now(self):
        self.sync.push()
        self._last_sync = time.time()

    def sync_if_due(self):
        if time.time() - self._last_sync > SYNC_INTERVAL:
            self.sync.push()
            self._last_sync = time.time()

    def full_stats(self) -> dict:
        revenue = self.get_revenue_stats()
        return {
            "identity":    self.get_identity().get("callsign", "Boss"),
            "clients":     len(self.get_all_clients()),
            "jobs":        revenue["completed_jobs"],
            "active_jobs": revenue["active_jobs"],
            "revenue":     revenue,
            "last_sync":   datetime.fromtimestamp(self._last_sync).strftime("%H:%M:%S"),
            "db_path":     DB_PATH,
        }


# Singleton — import this everywhere
memory = MemoryManager()
