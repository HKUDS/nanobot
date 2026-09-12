"""Versioned development records; evidence is distinct from an agent's notes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobStage = Literal["queued", "baseline", "building", "checking", "review", "ready", "deployed", "failed", "cancelled", "held"]


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    description: str = Field(min_length=1, max_length=4000)


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: list[str]
    exit_code: int
    elapsed_seconds: float
    log_file: str
    log_sha256: str
    source_sha256: str


class DevelopmentJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    objective: str
    evidence: list[str]
    acceptance: list[str]
    requirement_ids: list[str] = Field(default_factory=list)
    stage: JobStage = "queued"
    created_at: float
    updated_at: float
    base_commit: str | None = None
    baseline_sha256: str | None = None
    checkpoint_stage: JobStage | None = None
    build_attempts: int = 0
    candidate_path: str | None = None
    candidate_sha256: str | None = None
    artifact_path: str | None = None
    checks: list[list[str]] = Field(default_factory=list)
    baseline: list[CheckResult] = Field(default_factory=list)
    verification: list[CheckResult] = Field(default_factory=list)
    review: str | None = None
    review_accepted: bool = False
    repair_attempts: int = 0
    blocked_reason: str | None = None
    worker_pid: int | None = None
    worker_start_ticks: str | None = None
    token_usage: int = 0
    notes: list[str] = Field(default_factory=list)


class DevelopmentProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    objective: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    paused: bool = True
    updated_at: float = 0
    jobs: list[DevelopmentJob] = Field(default_factory=list)
    # Reservations survive a crash; unknown usage is conservatively charged.
    daily_tokens: dict[str, int] = Field(default_factory=dict)
    reservations: dict[str, tuple[str, int]] = Field(default_factory=dict)
