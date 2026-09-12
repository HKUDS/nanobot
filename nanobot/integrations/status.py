"""Read-only, bounded status probes. Configuration is never reported as liveness."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from nanobot.config.schema import Config
from nanobot.integrations.credentials import private_path


def memory_status(config: Config) -> dict[str, Any]:
    semantic = config.agents.defaults.semantic_memory
    result: dict[str, Any] = {
        "enabled": semantic.enabled, "rerank_mode": semantic.rerank_mode,
        "items": None, "status": "disabled" if not semantic.enabled else "unavailable",
    }
    if not semantic.enabled:
        return result
    try:
        import psycopg

        from nanobot.semantic_memory.service import SemanticMemoryService
        namespace = hashlib.sha256(
            f"{semantic.namespace or ''}\0{config.workspace_path.resolve()}".encode()
        ).hexdigest()[:32]
        with psycopg.connect(
            SemanticMemoryService._resolve_dsn(semantic), connect_timeout=2,  # pyright: ignore[reportPrivateUsage]
            options="-c default_transaction_read_only=on -c statement_timeout=1500",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM nanobot_memory.items WHERE workspace_namespace=%s", (namespace,))
                row = cursor.fetchone()
        if row is not None:
            result.update(items=int(row[0]), status="index_available")
    except Exception:
        # No provider exception/DSN can reach logs or responses.
        pass
    return result


def evolution_status(config: Config) -> dict[str, Any]:
    evolution = config.agents.defaults.evolution
    result: dict[str, Any] = {
        "enabled": evolution.enabled, "mode": evolution.mode,
        "capture_content": evolution.capture_content,
        "experiences": None, "status": "disabled" if not evolution.enabled else "no_data",
    }
    try:
        path = private_path(config.workspace_path, f"{evolution.storage_dir}/observations/experiences.jsonl")
        if not path.exists():
            return result
        if path.stat().st_size > 8_000_000:
            result["status"] = "log_over_read_limit"
            return result
        count = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    count += bool(cast(dict[str, Any], value).get("id"))
        result.update(experiences=count, status="observations_available")
    except (OSError, ValueError, RuntimeError):
        result["status"] = "unavailable"
    return result


def service_status(workspace: Path) -> list[dict[str, str]]:
    rows = [{"id": "gateway", "label": "Gateway", "state": "responding",
             "detail": f"Proces obsługujący panel: PID {os.getpid()}."}]
    binary = shutil.which("systemctl")
    for name, label in (("nanobot-mail-worker", "Worker poczty"), ("carillon", "Carillon"),
                        ("nanobot-time-manager", "Monitor iCloud")):
        state = "unknown"
        detail = "Brak potwierdzonego stanu procesu; zapis konfiguracji nie oznacza uruchomienia."
        if binary:
            # Fixed names only, never a shell or a user supplied unit/command.
            for user_scope in (False, True):
                try:
                    command = [binary, *(["--user"] if user_scope else []), "show", name + ".service",
                               "--property=LoadState,ActiveState", "--no-pager"]
                    completed = subprocess.run(command, capture_output=True, timeout=1, check=False)
                    text = completed.stdout[:4096].decode(errors="replace")
                    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
                    if completed.returncode == 0 and fields.get("LoadState") == "loaded":
                        active = fields.get("ActiveState")
                        if active in {"active", "inactive", "failed", "activating", "deactivating"}:
                            state = active
                            detail = "Stan jednostki systemd" + (" użytkownika." if user_scope else " systemowej.")
                            break
                except (OSError, subprocess.TimeoutExpired):
                    continue
        rows.append({"id": name, "label": label, "state": state, "detail": detail})
    return rows
