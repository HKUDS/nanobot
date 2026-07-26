"""Package discovery for nanobot, Pi, and OpenClaw extension ecosystems."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

_SEARCHES = {
    "nanobot": "keywords:nanobot-extension",
    "pi": "keywords:pi-package",
    "openclaw": "keywords:openclaw-plugin",
}


@dataclass(frozen=True, slots=True)
class MarketplacePackage:
    """One untrusted package candidate returned by a public package index."""

    name: str
    version: str
    description: str
    ecosystem: str
    publisher: str = ""
    license: str = ""
    homepage: str = ""
    repository: str = ""
    published_at: str = ""


class ExtensionMarketplace:
    """Search npm without making package installation an implicit trust action."""

    def search(
        self,
        query: str = "",
        *,
        ecosystem: str = "all",
        limit: int = 30,
    ) -> tuple[MarketplacePackage, ...]:
        if ecosystem != "all" and ecosystem not in _SEARCHES:
            raise ValueError(f"unknown extension ecosystem: {ecosystem}")
        if not 1 <= limit <= 100:
            raise ValueError("market search limit must be between 1 and 100")
        ecosystems = _SEARCHES if ecosystem == "all" else {ecosystem: _SEARCHES[ecosystem]}
        found: dict[str, MarketplacePackage] = {}
        for name, keyword in ecosystems.items():
            terms = " ".join(part for part in (keyword, query.strip()) if part)
            for row in _npm_search(terms, limit=limit):
                required_keyword = keyword.partition(":")[2]
                keywords = row.get("keywords")
                if not isinstance(keywords, list) or required_keyword not in keywords:
                    continue
                package = _marketplace_package(row, ecosystem=name)
                if not package.name or not package.version:
                    continue
                found.setdefault(package.name, package)
        return tuple(
            sorted(found.values(), key=lambda item: (item.ecosystem, item.name))[:limit]
        )


def _npm_search(query: str, *, limit: int) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["npm", "search", "--json", f"--searchlimit={limit}", "--", query],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("npm is required to search the extension marketplace") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("extension marketplace search timed out") from exc
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout).strip()
        raise RuntimeError(message or "extension marketplace search failed") from exc
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("npm returned an invalid marketplace response") from exc
    if not isinstance(value, list):
        raise RuntimeError("npm returned an invalid marketplace response")
    return [row for row in value if isinstance(row, dict)]


def _marketplace_package(row: dict[str, Any], *, ecosystem: str) -> MarketplacePackage:
    publisher = row.get("publisher")
    publisher_name = publisher.get("username", "") if isinstance(publisher, dict) else ""
    links = row.get("links")
    links = links if isinstance(links, dict) else {}
    return MarketplacePackage(
        name=str(row.get("name") or ""),
        version=str(row.get("version") or ""),
        description=str(row.get("description") or ""),
        ecosystem=ecosystem,
        publisher=str(publisher_name),
        license=str(row.get("license") or ""),
        homepage=str(links.get("homepage") or ""),
        repository=str(links.get("repository") or ""),
        published_at=str(row.get("date") or ""),
    )
