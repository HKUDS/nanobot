"""Non-secret, validated configuration of personal background integrations."""
from __future__ import annotations

import ipaddress
import re
from datetime import time
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ConfigDict, Field, field_validator, model_validator

from nanobot.config.integration_slots import IntegrationSlot
from nanobot.config_base import Base


class IntegrationModel(Base):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ICloudIntegrationConfig(IntegrationModel):
    username: str = Field(default="", max_length=320)
    credential_ref: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    timezone: str = "Europe/Warsaw"
    management_calendar: str = Field(default="Nanobot", min_length=1, max_length=120)
    sleep_hours: float = Field(default=8, ge=4, le=12)
    default_wake_time: str = "07:00"
    morning_preparation_minutes: int = Field(default=90, ge=0, le=360)
    briefing_minutes_after_wake: int = Field(default=20, ge=0, le=180)
    auto_manage_sleep: bool = False

    @field_validator("username", "management_calendar")
    @classmethod
    def clean_text(cls, value: str) -> str:
        if any(ord(c) < 32 for c in value):
            raise ValueError("control characters are not allowed")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("invalid timezone") from exc
        return value

    @field_validator("default_wake_time")
    @classmethod
    def local_clock(cls, value: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", value):
            raise ValueError("use HH:MM")
        time.fromisoformat(value)
        return value

    @field_validator("management_calendar")
    @classmethod
    def named_calendar(cls, value: str) -> str:
        if value.casefold() == "auto" or "://" in value:
            raise ValueError("a dedicated calendar name is required")
        return value


class MailRuleConfig(IntegrationModel):
    name: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=200)
    sender_globs: list[str] = Field(default_factory=list, max_length=30)
    subject_contains: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def conditions(self) -> MailRuleConfig:
        values = [self.name, self.destination, *self.sender_globs, *self.subject_contains]
        if not (self.sender_globs or self.subject_contains):
            raise ValueError("a rule requires a condition")
        if any(not v.strip() or len(v) > 300 or any(ord(c) < 32 for c in v) for v in values):
            raise ValueError("invalid rule text")
        return self


class MailAccountConfig(IntegrationModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    email: str = Field(min_length=3, max_length=320)
    host: str = Field(min_length=3, max_length=253)
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=320)
    credential_ref: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    managed_by: Literal["icloud"] | None = None
    folder_policy: Literal["all", "allowlist"] = "all"
    allowed_folders: list[str] = Field(default_factory=list, max_length=100)
    rules: list[MailRuleConfig] = Field(default_factory=list, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_allowlist(cls, value: Any) -> Any:
        # Existing explicit restrictions remain restrictions. Empty/default lists
        # never mean "no mailbox access"; new accounts discover all folders.
        if not isinstance(value, dict):
            return value
        data = cast(dict[Any, Any], value)  # checked mapping; Pydantic validates its fields below
        if "folder_policy" not in data and "folderPolicy" not in data:
            if data.get("allowed_folders") or data.get("allowedFolders"):
                return {**data, "folder_policy": "allowlist"}
        return data

    @field_validator("host")
    @classmethod
    def public_hostname(cls, value: str) -> str:
        value = value.strip().lower().encode("idna").decode("ascii")
        # No arbitrary URL, local service, command argument or numeric host in the UI.
        try:
            ipaddress.ip_address(value)
        except ValueError:
            pass
        else:
            raise ValueError("use a public mail server hostname")
        if (not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value)
                or "." not in value or ".." in value
                or value.endswith((".local", ".localhost", ".internal", ".test", ".invalid"))):
            raise ValueError("invalid public hostname")
        return value

    @field_validator("email", "username")
    @classmethod
    def text_value(cls, value: str) -> str:
        if any(ord(c) < 32 for c in value):
            raise ValueError("control characters are not allowed")
        return value.strip()

    @model_validator(mode="after")
    def validate_folder_policy(self) -> MailAccountConfig:
        if "@" not in self.email:
            raise ValueError("invalid email address")
        if len(self.allowed_folders) != len(set(self.allowed_folders)):
            raise ValueError("duplicate folders")
        for folder in self.allowed_folders:
            if (not folder.strip() or len(folder) > 200 or folder.startswith("-")
                    or any(ord(c) < 32 for c in folder)):
                raise ValueError("invalid folder")
        for rule in self.rules:
            if rule.destination.startswith("-"):
                raise ValueError("invalid rule destination")
        if self.folder_policy == "allowlist" and any(
            rule.destination not in self.allowed_folders for rule in self.rules
        ):
            raise ValueError("rule destination must be in the folder allowlist")
        if self.managed_by == "icloud" and (self.host, self.port) != ("imap.mail.me.com", 993):
            raise ValueError("iCloud mail requires its fixed IMAPS endpoint")
        return self


class PersonalIntegrationsConfig(IntegrationModel):
    motis: IntegrationSlot = Field(default_factory=IntegrationSlot)
    firefly_iii: IntegrationSlot = Field(default_factory=IntegrationSlot)
    icloud: ICloudIntegrationConfig = Field(default_factory=ICloudIntegrationConfig)
    mail_accounts: list[MailAccountConfig] = Field(default_factory=list, max_length=20)
    reconcile_interval_seconds: int = Field(default=180, ge=120, le=300)

    @model_validator(mode="after")
    def unique_accounts(self) -> PersonalIntegrationsConfig:
        ids = [account.id for account in self.mail_accounts]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate mail account IDs")
        linked = [account for account in self.mail_accounts if account.managed_by == "icloud"]
        if len(linked) > 1:
            raise ValueError("duplicate linked iCloud account")
        if linked and (linked[0].username, linked[0].credential_ref) != (
            self.icloud.username, self.icloud.credential_ref
        ):
            raise ValueError("linked iCloud credentials must share the Apple source")
        return self
