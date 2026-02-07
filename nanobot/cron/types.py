"""Cron types (Pydantic models with camelCase JSON aliases)."""

from typing import Literal

from pydantic import BaseModel, Field


class CronSchedule(BaseModel):
    """Schedule definition for a cron job."""

    kind: Literal["at", "every", "cron"]
    at_ms: int | None = Field(None, alias="atMs")
    every_ms: int | None = Field(None, alias="everyMs")
    expr: str | None = None
    tz: str | None = None

    model_config = {"populate_by_name": True}


class CronPayload(BaseModel):
    """What to do when the job runs."""

    kind: Literal["system_event", "agent_turn"] = "agent_turn"
    message: str = ""
    deliver: bool = False
    channel: str | None = None
    to: str | None = None


class CronJobState(BaseModel):
    """Runtime state of a job."""

    next_run_at_ms: int | None = Field(None, alias="nextRunAtMs")
    last_run_at_ms: int | None = Field(None, alias="lastRunAtMs")
    last_status: Literal["ok", "error", "skipped"] | None = Field(
        None, alias="lastStatus"
    )
    last_error: str | None = Field(None, alias="lastError")

    model_config = {"populate_by_name": True}


class CronJob(BaseModel):
    """A scheduled job."""

    id: str
    name: str
    enabled: bool = True
    schedule: CronSchedule = CronSchedule(kind="every")
    payload: CronPayload = CronPayload()
    state: CronJobState = CronJobState()
    created_at_ms: int = Field(0, alias="createdAtMs")
    updated_at_ms: int = Field(0, alias="updatedAtMs")
    delete_after_run: bool = Field(False, alias="deleteAfterRun")

    model_config = {"populate_by_name": True}


class CronStore(BaseModel):
    """Persistent store for cron jobs."""

    version: int = 1
    jobs: list[CronJob] = []
