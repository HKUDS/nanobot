"""Inert connection slots; saving one never enables network or financial actions."""
from __future__ import annotations

import ipaddress
from typing import Literal
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, field_validator

from nanobot.config_base import Base


class IntegrationSlot(Base):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: Literal[False] = False  # No runtime adapter is installed yet.
    base_url: str = Field(default="", max_length=2048)
    credential_ref: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    read_only: Literal[True] = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return value
        if any(ord(c) < 33 for c in value) or "\\" in value or "%" in value:
            raise ValueError("invalid endpoint")
        parsed = urlsplit(value)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment):
            raise ValueError("use a base HTTP(S) URL without credentials, query or fragment")
        if parsed.port == 0:
            raise ValueError("invalid port")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address and (address.is_link_local or address.is_unspecified or address.is_multicast):
            raise ValueError("unsupported endpoint address")
        if parsed.scheme == "http" and not (
            parsed.hostname == "localhost" or address and (address.is_private or address.is_loopback)
        ):
            raise ValueError("remote endpoints require HTTPS")
        return value.rstrip("/")
