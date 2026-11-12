"""Instance-scoped outbound proxy configuration."""

import os
import re
from typing import Any, cast
from urllib.parse import quote, urlsplit

from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError

from nanobot.config_base import Base

_ENV_REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class NetworkConfig(Base):
    proxy: str | None = Field(default=None, repr=False)

    @field_validator("proxy")
    @classmethod
    def normalize_proxy(cls, value: str | None) -> str | None:
        value = value.strip() if value else ""
        if not value:
            return None
        if "://" not in value and not _ENV_REF_PATTERN.fullmatch(value):
            value = f"http://{value}"
        if "${" in value:
            return value
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme in {"http", "https", "socks5", "socks5h"}
                and bool(parsed.hostname)
                and parsed.port != 0
                and not parsed.query
                and not parsed.fragment
                and parsed.path in {"", "/"}
                and not any(char.isspace() for char in value)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Enter an HTTP, HTTPS or SOCKS5 proxy URL")
        return value

    def resolve_environment(self) -> str | None:
        value = self.proxy or ""
        userinfo_start = value.find("://") + 3
        userinfo_end = value.rfind("@")

        def replace(match: re.Match[str]) -> str:
            resolved = os.environ[match[1]]
            if userinfo_start <= match.start() < userinfo_end:
                if match.start() == userinfo_start and match.end() == userinfo_end:
                    # Whole userinfo supplies its own delimiter and URL escapes.
                    username, separator, password = resolved.partition(":")
                    return f"{quote(username, safe='%')}{separator}{quote(password, safe='%')}"
                return quote(resolved, safe="")
            return resolved

        try:
            return self.normalize_proxy(_ENV_REF_PATTERN.sub(replace, value))
        except KeyError:
            raise ValueError("The shared proxy environment variable is not set") from None

    def resolve_proxy(self, enabled: bool) -> str | None:
        if not enabled:
            return None
        proxy = self.resolve_environment()
        if not proxy:
            raise ValueError("Configure the shared proxy in Advanced before enabling it")
        return proxy


def _config_object(value: object) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def migrate_legacy_proxy_config(value: Any) -> Any:
    """Consolidate legacy addresses after settings sources have been merged."""
    if not isinstance(value, dict):
        return value
    data = cast(dict[str, Any], value)
    sections: list[dict[str, Any]] = []
    providers = _config_object(data.get("providers")) or {}
    sections.extend(section for value in providers.values() if (section := _config_object(value)) is not None)
    tools = _config_object(data.get("tools")) or {}
    if (web := _config_object(tools.get("web"))) is not None:
        sections.append(web)
    channels = _config_object(data.get("channels")) or {}
    sections.extend(section for name in ("telegram", "discord", "slack", "matrix", "whatsapp") if (section := _config_object(channels.get(name))) is not None)

    network = data.get("network")
    explicit_proxy = isinstance(network, NetworkConfig) or isinstance(network, dict) and "proxy" in network
    addresses: set[str] = set()
    migrated: list[dict[str, Any]] = []
    for section in sections:
        raw = section.get("proxy")
        if isinstance(raw, str) and raw.strip():
            if not explicit_proxy:
                proxy = NetworkConfig.normalize_proxy(raw)
                assert proxy is not None
                username = section.get("proxyUsername", section.get("proxy_username"))
                password = section.get("proxyPassword", section.get("proxy_password"))
                if isinstance(username, str) and username and isinstance(password, str) and password:
                    if _ENV_REF_PATTERN.fullmatch(proxy):
                        raise PydanticCustomError("proxy_credential_migration", "Combine the Discord proxy URL and credentials into one full URL environment variable, or set network.proxy before upgrading.")
                    scheme, host = proxy.split("://", 1)
                    host = host.rsplit("@", 1)[-1]
                    credentials = f"{quote(username, safe='${}')}:{quote(password, safe='${}')}"
                    proxy = f"{scheme}://{credentials}@{host}"
                addresses.add(proxy)
            migrated.append(section)

    if addresses:
        if len(addresses) > 1:
            raise PydanticCustomError("proxy_address_migration", "Multiple legacy proxy addresses are no longer supported. Set network.proxy to one address before upgrading.")
        if not isinstance(network, dict):
            network = {}
            data["network"] = network
        network["proxy"] = next(iter(addresses))
    for section in sections:
        for key in ("proxy", "proxyUsername", "proxy_username", "proxyPassword", "proxy_password"):
            section.pop(key, None)
    for section in migrated:
        if "useProxy" not in section and "use_proxy" not in section:
            section["useProxy"] = True
    return data
