"""Pydantic request and response models for the nanobot web API."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    message: str
    session_id: str = "web:default"


class AddCronJobRequest(BaseModel):
    name: str
    message: str
    every_seconds: int | None = None
    cron_expr: str | None = None
    at_iso: str | None = None
    deliver: bool = False
    channel: str | None = None
    to: str | None = None

    @field_validator("name", "message")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v


class ToggleCronJobRequest(BaseModel):
    enabled: bool
