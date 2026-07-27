"""Dependency-free Matrix configuration model shared by validation and runtime."""

import sys
from typing import Literal

from pydantic import Field

from nanobot.config.schema import Base


class MatrixConfig(Base):
    """Matrix (Element) channel configuration."""

    enabled: bool = False
    homeserver: str = "https://matrix.org"
    user_id: str = ""
    password: str = ""
    access_token: str = ""
    device_id: str = ""
    e2ee_enabled: bool = Field(default=sys.platform != "win32", alias="e2eeEnabled")
    sas_verification: bool = Field(default=False, alias="sasVerification")
    sync_stop_grace_seconds: int = 2
    max_media_bytes: int = 20 * 1024 * 1024
    max_concurrent_media_downloads: int = 2
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["open", "mention", "allowlist"] = "open"
    group_allow_from: list[str] = Field(default_factory=list)
    allow_room_mentions: bool = False
    streaming: bool = False


__all__ = ["MatrixConfig"]
