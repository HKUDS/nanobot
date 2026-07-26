"""Transport-neutral extension management service."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any

from nanobot.extensions.host import ExtensionHost
from nanobot.extensions.market import ExtensionMarketplace
from nanobot.extensions.registry import ExtensionCandidate, ExtensionScope
from nanobot.extensions.store import ExtensionStore


class ExtensionService:
    """One management boundary shared by CLI and WebUI."""

    def __init__(
        self,
        *,
        host: ExtensionHost | None = None,
        store: ExtensionStore | None = None,
        marketplace: ExtensionMarketplace | None = None,
    ) -> None:
        self.host = host
        self.store = store or ExtensionStore()
        self.marketplace = marketplace or ExtensionMarketplace()
        self._mutation_lock = asyncio.Lock()

    async def status(self) -> dict[str, Any]:
        catalog = self.host.snapshot.catalog if self.host and self.host.snapshot else None
        if catalog is None:
            discovery = self.store.discover()
            candidates = discovery.candidates
            diagnostics = discovery.diagnostics
            active_ids: set[str] = set()
        else:
            candidates = catalog.candidates
            diagnostics = catalog.diagnostics
            active_ids = {
                active.candidate.manifest.id
                for active in self.host.snapshot.activation.extensions
            }
            active_ids.update(
                candidate.manifest.id
                for candidate in catalog.snapshot.extensions
                if candidate.location is None
            )
            if self.host and self.host.snapshot:
                diagnostics += self.host.snapshot.activation.diagnostics
        records = self.store.records()
        return {
            "extensions": [
                _candidate_payload(candidate, active_ids, records.get(candidate.manifest.id))
                for candidate in sorted(
                    candidates,
                    key=lambda item: (item.scope, item.manifest.name.lower()),
                )
            ],
            "diagnostics": [asdict(item) for item in diagnostics],
        }

    async def search(
        self,
        query: str = "",
        *,
        ecosystem: str = "all",
        limit: int = 30,
    ) -> dict[str, Any]:
        packages = await asyncio.to_thread(
            self.marketplace.search,
            query,
            ecosystem=ecosystem,
            limit=limit,
        )
        return {"packages": [asdict(package) for package in packages]}

    async def install(
        self,
        source: str,
        *,
        kind: str = "npm",
        ref: str = "",
        trusted: bool = False,
    ) -> dict[str, Any]:
        async with self._mutation_lock:
            if kind == "npm":
                result = await asyncio.to_thread(
                    self.store.install_npm,
                    source,
                    trusted=trusted,
                )
            elif kind == "git":
                result = await asyncio.to_thread(
                    self.store.install_git,
                    source,
                    ref=ref,
                    trusted=trusted,
                )
            elif kind == "local":
                result = await asyncio.to_thread(
                    self.store.install_local,
                    Path(source),
                    trusted=trusted,
                )
            else:
                raise ValueError(f"unknown extension source kind: {kind}")
            await self._reload()
            return {
                "record": _record_payload(result.record),
                "manifest": _manifest_payload(result.package.manifest),
                "diagnostics": list(result.package.diagnostics),
            }

    async def set_enabled(self, extension_id: str, enabled: bool) -> dict[str, Any]:
        return await self._update(extension_id, self.store.set_enabled, enabled)

    async def set_trusted(self, extension_id: str, trusted: bool) -> dict[str, Any]:
        return await self._update(extension_id, self.store.set_trusted, trusted)

    async def set_permissions(
        self,
        extension_id: str,
        permissions: set[str] | frozenset[str],
    ) -> dict[str, Any]:
        return await self._update(
            extension_id,
            self.store.set_permissions,
            permissions,
        )

    async def uninstall(self, extension_id: str) -> dict[str, Any]:
        async with self._mutation_lock:
            await asyncio.to_thread(self.store.uninstall, extension_id)
            await self._reload()
            return {"removed": extension_id}

    async def _update(self, extension_id: str, action: Any, value: Any) -> dict[str, Any]:
        async with self._mutation_lock:
            record = await asyncio.to_thread(action, extension_id, value)
            await self._reload()
            return {"record": _record_payload(record)}

    async def _reload(self) -> None:
        if self.host is not None:
            await self.host.reload()


def _candidate_payload(
    candidate: ExtensionCandidate,
    active_ids: set[str],
    record: Any | None,
) -> dict[str, Any]:
    manifest = candidate.manifest
    requested = [permission.name for permission in manifest.permissions]
    return {
        **_manifest_payload(manifest),
        "scope": candidate.scope.name.lower(),
        "location": str(candidate.location) if candidate.location else None,
        "enabled": candidate.enabled,
        "trusted": candidate.trusted,
        "active": manifest.id in active_ids,
        "requested_permissions": requested,
        "granted_permissions": sorted(candidate.granted_permissions),
        "source": record.source.value if record else (
            "builtin" if candidate.scope is ExtensionScope.BUILTIN else "path"
        ),
        "source_ref": record.source_ref if record else "",
        "integrity": record.integrity if record else "",
        "installed_at": record.installed_at if record else "",
        "managed_by_store": record is not None,
    }


def _manifest_payload(manifest: Any) -> dict[str, Any]:
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "runtime": manifest.runtime.value,
        "description": manifest.description,
        "homepage": manifest.homepage,
        "license": manifest.license,
        "contributions": [
            {
                "kind": contribution.kind.value,
                "name": contribution.name,
                "description": contribution.description,
            }
            for contribution in manifest.contributions
        ],
        "dependencies": [
            {
                "kind": dependency.kind.value,
                "name": dependency.name,
                "specifier": dependency.specifier,
                "optional": dependency.optional,
            }
            for dependency in manifest.dependencies
        ],
        "permissions": [
            {"name": permission.name, "reason": permission.reason}
            for permission in manifest.permissions
        ],
    }


def _record_payload(record: Any) -> dict[str, Any]:
    return {
        **asdict(record),
        "source": record.source.value,
    }
