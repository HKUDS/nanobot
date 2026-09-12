"""Read authoritative Codex account quotas through the documented app-server API.

This adapter never starts a model turn, redeems reset credits, changes login, or
exports credentials. Account quotas are separate from nanobot's token accounting.
"""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import time
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nanobot.config_base import Base
from nanobot.operations.state import read_state, write_state


class CodexLimitsConfig(Base):
    enable: bool = False
    owner_session_key: str = ""
    executable: str = "codex"
    refresh_seconds: int = Field(default=60, ge=30, le=3600)

    @model_validator(mode="after")
    def require_owner(self) -> CodexLimitsConfig:
        if self.enable and not self.owner_session_key:
            raise ValueError("Codex limits require an owner session")
        return self


class QuotaWindow(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False, populate_by_name=True)
    used_percent: float = Field(alias="usedPercent", ge=0, le=10_000)
    window_duration_mins: int | None = Field(alias="windowDurationMins", default=None, gt=0)
    resets_at: int | None = Field(alias="resetsAt", default=None, gt=0)


class QuotaBucket(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    limit_id: str = Field(alias="limitId", min_length=1, max_length=200)
    limit_name: str | None = Field(alias="limitName", default=None, max_length=200)
    primary: QuotaWindow | None = None
    secondary: QuotaWindow | None = None
    plan_type: str | None = Field(alias="planType", default=None, max_length=100)
    rate_limit_reached_type: str | None = Field(alias="rateLimitReachedType", default=None, max_length=200)


class QuotaSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    source: str = "codex_app_server"
    state: Literal["available", "stale", "unavailable", "disabled"] = "unavailable"
    observed_at: float | None = None
    attempted_at: float | None = None
    account_fingerprint: str | None = None
    gateway_account_matches: bool | None = None
    buckets: list[QuotaBucket] = Field(default_factory=list)
    error: str | None = None


def parse_limits(payload: object, *, now: float, gateway_account: str | None) -> QuotaSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("invalid limits response")
    raw = cast(dict[str, Any], payload)
    multiple = raw.get("rateLimitsByLimitId")
    if isinstance(multiple, dict) and multiple:
        entries = list(cast(dict[str, object], multiple).items())
    else:
        entries = [("codex", raw.get("rateLimits"))]
    if len(entries) > 50:
        raise ValueError("too many quota buckets")
    buckets: list[QuotaBucket] = []
    for identity, value in entries:
        if not isinstance(value, dict):
            raise ValueError("invalid quota bucket")
        bucket = QuotaBucket.model_validate({"limitId": identity, **cast(dict[str, Any], value)})
        if bucket.primary is not None or bucket.secondary is not None:
            buckets.append(bucket)
    if not buckets:
        raise ValueError("provider did not return any quota windows")
    account = raw.get("accountId")
    account_id = account if isinstance(account, str) and account else None
    return QuotaSnapshot(state="available", observed_at=now, attempted_at=now, buckets=buckets,
                         account_fingerprint=hashlib.sha256(account_id.encode()).hexdigest()[:16] if account_id else None,
                         gateway_account_matches=(account_id == gateway_account) if account_id and gateway_account else None)


async def read_app_server(executable: str) -> object:
    binary = shutil.which(executable)
    if binary is None:
        raise ValueError("codex_cli_unavailable")
    process = await asyncio.create_subprocess_exec(
        binary, "app-server", "--stdio", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True, limit=2_000_000, cwd=str(Path.home()),
    )
    assert process.stdin is not None and process.stdout is not None
    async def send(value: dict[str, Any]) -> None:
        assert process.stdin is not None
        process.stdin.write((json.dumps(value) + "\n").encode())
        await process.stdin.drain()

    async def result(identity: int) -> object:
        assert process.stdout is not None
        for _ in range(200):
            line = await process.stdout.readline()
            if not line:
                raise ValueError("codex_app_server_closed")
            raw: object = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError("codex_app_server_invalid_response")
            response = cast(dict[str, Any], raw)
            if response.get("id") == identity:
                if "error" in response:
                    raise ValueError("codex_account_limits_unavailable")
                return response.get("result")
            # No server-requested action is approved by this read-only client.
            if "id" in response and "method" in response:
                await send({"id": response["id"], "error": {"code": -32601, "message": "Read-only quota client"}})
        raise ValueError("codex_app_server_notification_limit")

    try:
        async with asyncio.timeout(20):
            await send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "nanobot_limits", "version": "0.1"},
            }})
            await result(1)
            await send({"method": "initialized", "params": {}})
            await send({"id": 2, "method": "account/rateLimits/read"})
            return await result(2)
    finally:
        if process.returncode is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                await asyncio.wait_for(process.wait(), 3)
            except ProcessLookupError:
                await process.wait()
            except TimeoutError:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                await process.wait()


class CodexLimits:
    def __init__(self, config: CodexLimitsConfig, path: Path) -> None:
        self.config, self.path = config, path
        self._lock = asyncio.Lock()

    async def snapshot(self) -> QuotaSnapshot:
        if not self.config.enable:
            return QuotaSnapshot(enabled=False, state="disabled")
        async with self._lock:
            now = time.time()
            try:
                stored = read_state(self.path)
                previous = QuotaSnapshot.model_validate(stored) if stored else QuotaSnapshot()
            except (ValueError, OSError):
                previous = QuotaSnapshot()
            if previous.attempted_at and 0 <= now - previous.attempted_at < self.config.refresh_seconds:
                if previous.observed_at and now - previous.observed_at >= self.config.refresh_seconds * 2:
                    previous.state = "stale"
                return previous
            try:
                from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
                from oauth_cli_kit.storage import FileTokenStorage

                token = await asyncio.to_thread(FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename).load)
                account = getattr(token, "account_id", None)
                current = parse_limits(await read_app_server(self.config.executable), now=time.time(),
                                       gateway_account=account if isinstance(account, str) else None)
            except (ValueError, OSError, TimeoutError):
                current = previous.model_copy(update={"attempted_at": now,
                                                      "state": "stale" if previous.buckets else "unavailable",
                                                      "error": "Odczyt limitów Codex jest chwilowo niedostępny."})
            write_state(self.path, current.model_dump(mode="json"))
            return current


def limits_report(snapshot: QuotaSnapshot) -> str:
    if not snapshot.enabled:
        return "Podgląd limitów Codex jest wyłączony."
    lines = ["Limity konta Codex CLI" + (" — dane nieaktualne" if snapshot.state == "stale" else "")]
    if snapshot.gateway_account_matches is False:
        lines.append("To inne konto niż konto Codex używane przez gateway.")
    for bucket in snapshot.buckets:
        for label, window in (("główne", bucket.primary), ("dodatkowe", bucket.secondary)):
            if window is None:
                continue
            duration = f", okno {window.window_duration_mins} min" if window.window_duration_mins else ""
            reset = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(window.resets_at)) if window.resets_at else "brak danych"
            lines.append(f"{bucket.limit_name or bucket.limit_id} ({label}{duration}): {window.used_percent:g}% wykorzystane; odnowienie {reset}.")
    if snapshot.observed_at:
        lines.append("Odczyt: " + time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(snapshot.observed_at)))
    if snapshot.error:
        lines.append(snapshot.error)
    return "\n".join(lines)
