import os
import re
from urllib.parse import quote, urlsplit

from pydantic import Field, field_validator

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
