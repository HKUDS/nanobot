"""Local connection directory. Owns SSH tunnels, never remote gateway lifetimes."""

from __future__ import annotations

import asyncio
import json
import secrets
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import httpx
from pydantic import Field

from nanobot.utils.helpers import _write_text_atomic  # pyright: ignore[reportPrivateUsage]
from nanobot.webui import remote_ssh
from nanobot.webui.client_contract import Compatibility, assess_webui_contract, compatibility_error
from nanobot.webui.remote_proxy import RemoteProxy
from nanobot.webui.remote_ssh import RemoteError, RemoteProfile, Tunnel

_HEALTH_TIMEOUT_SECONDS = 12


class _SavedProfile(RemoteProfile):
    # Retain an origin per server so browser preferences/caches cannot drift
    # between servers on every reconnect. Not an editable API field.
    local_port: int = Field(default=0, ge=0, le=65535)
    proxy_origin: bool = False
    local_client_origin: bool = False
    pair_id: str = ""


@dataclass
class Connection:
    tunnel: Tunnel
    secret: str
    hostname: str
    config_path: str
    gateway_id: str
    proxy: RemoteProxy
    error: str = ""
    paired: bool = False


class RemoteInstances:
    """List/save/connect/disconnect with credentials confined to live connections."""

    def __init__(self, directory: Path, *, local_gateway_id: str = "") -> None:
        self.path = directory / "remote-instances.json"
        self.local_gateway_id = local_gateway_id
        # Public identity, not an authentication capability. A new local manager
        # cannot renew a cached iframe's old proxy credentials after restart.
        self._view_session = uuid.uuid4().hex
        self.connections: dict[str, Connection] = {}
        self._proxies: dict[int, RemoteProxy] = {}
        self._lock = asyncio.Lock()
        self._picker_lock = asyncio.Lock()
        self._unverified: dict[str, tuple[str, str, float]] = {}
        self._unknown_hosts: set[str] = set()
        self._closed = False
        self._compatibility: dict[str, Compatibility] = {}
        from nanobot.webui.remote_pairing import PairStore

        self.pairing = PairStore(directory)

    def _known_hosts(self, key: str) -> Path:
        return self.path.parent / "remote-hosts" / key

    def resume(self) -> None:
        """Allow a reused local channel to start again after its stop completed."""
        self._closed = False

    def _read(self) -> dict[str, _SavedProfile]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError
            profiles = {str(uuid.UUID(key)): _SavedProfile.model_validate(value)
                        for key, value in cast(dict[str, Any], raw).items()}
            for profile in profiles.values():
                if profile.pair_id:
                    # These are managed files, not external SSH settings. Resolve
                    # them from the current root after a backup restore or move.
                    directory = self.pairing.path(profile.pair_id)
                    profile.identity_file = str(directory / "identity")
                    if profile.ssh_config:
                        profile.ssh_config = str(directory / "ssh_route")
            return profiles
        except (ValueError, TypeError, OSError):
            raise RemoteError("profile_store_invalid") from None

    def _write(self, profiles: dict[str, _SavedProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(self.path, json.dumps(
            {key: profile.model_dump() for key, profile in profiles.items()}, ensure_ascii=False,
        ))
        self.path.chmod(0o600)

    def _remember_origins(self, profiles: dict[str, _SavedProfile], port: int = 0) -> set[int]:
        # Browser storage outlives edits, Forget and gateway restarts. Keep a
        # small append-only port ledger, including pre-ledger saved profiles,
        # so a new target never inherits a retired target's browser origin.
        path = self.path.with_name("remote-origin-ports.json")
        try:
            raw: object = json.loads(path.read_text()) if path.exists() else []
            if not isinstance(raw, list):
                raise ValueError
            ports: set[int] = set()
            for value in cast(list[object], raw):
                if type(value) is not int or not 1 <= value <= 65535:
                    raise ValueError
                ports.add(value)
        except (ValueError, TypeError, OSError):
            raise RemoteError("profile_store_invalid") from None
        ports.update(profile.local_port for profile in profiles.values() if profile.local_port)
        if port:
            ports.add(port)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(path, json.dumps(sorted(ports)))
        path.chmod(0o600)
        return ports

    def snapshot(self) -> dict[str, Any]:
        profiles: list[dict[str, Any]] = []
        instances: dict[tuple[str, str, int, str, str, int, str, str], str] = {}
        for key, profile in self._read().items():
            connection = self.connections.get(key)
            error = (connection.error or ("" if connection.tunnel.active else "ssh_unreachable")) if connection else "disconnected"
            item = {"id": key, **profile.model_dump(exclude={"local_port", "proxy_origin", "local_client_origin", "pair_id"}),
                    "connected": connection is not None and not error,
                    "connection_error": error}
            if connection:
                item["gateway_id"] = connection.gateway_id
                item["view_id"] = self._view_session
            if key in self._compatibility:
                item["compatibility"] = self._compatibility[key]
                if not connection and (compatibility_failure := compatibility_error(self._compatibility[key])):
                    item["connection_error"] = compatibility_failure
            if profile.pair_id:
                item.update(paired=True, revoke_command=
                            f"nanobot remote revoke {profile.pair_id} --ssh-user {profile.host.split('@')[0]}")
                expiry = self.pairing.authorization_until(profile.pair_id)
                if expiry is not None:
                    item["authorized_until"] = expiry
                receipt = self.pairing.saved_receipt(profile.pair_id)
                if receipt is not None:
                    # Group only authenticated local receipt evidence, never
                    # display names, addresses alone, or transient gateway IDs.
                    item["instance_id"] = instances.setdefault(receipt.destination(), key)
            profiles.append(item)
        from nanobot import __version__

        return {"available": True, "machine_name": socket.gethostname(),
                "client_version": __version__, "profiles": profiles}

    async def health(self) -> dict[str, Any]:
        # Hold a lifetime lease through every credential-bearing request. Final
        # shutdown cannot release the listeners halfway through a health check.
        try:
            # Includes lock contention and all response reads, not just each
            # socket read. Return the directory before the browser's 20s budget.
            async with asyncio.timeout(_HEALTH_TIMEOUT_SECONDS):
                async with self._lock:
                    await asyncio.gather(*(self._check(item) for item in self.connections.values()))
        except TimeoutError:
            pass
        return self.snapshot()

    async def _check(self, connection: Connection) -> None:
        if not connection.tunnel.active:
            connection.error = "ssh_unreachable"
            return
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                response = await client.get(
                    f"http://127.0.0.1:{connection.tunnel.port}/webui/terminal",
                    headers={"X-Nanobot-Auth": connection.secret},
                )
            if response.status_code in {401, 403}:
                connection.error = "remote_auth_failed"
            elif response.status_code != 200:
                connection.error = "remote_unreachable"
            else:
                raw_identity = response.json()
                identity = cast(dict[str, Any], raw_identity) if isinstance(raw_identity, dict) else {}
                if (type(identity.get("protocolVersion")) is not int
                        or identity.get("protocolVersion") != 1 or not isinstance(identity.get("gatewayId"), str)):
                    connection.error = "incompatible_gateway"
                elif identity["gatewayId"] != connection.gateway_id:
                    connection.error = "instance_changed"
                else:
                    report = assess_webui_contract(identity.get("webui"))
                    for key, item in self.connections.items():
                        if item is connection:
                            self._compatibility[key] = report
                    connection.error = compatibility_error(report)
                    if connection.error:
                        await connection.proxy.pause()
        except (httpx.HTTPError, ValueError, AttributeError):
            connection.error = connection.tunnel.error or "remote_unreachable"
            if connection.paired and connection.error == "ssh_auth_failed":
                connection.error = "pair_authorization_rejected"
        except asyncio.CancelledError:
            connection.error = "remote_unreachable"
            raise

    async def action(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "pick_file":
            from nanobot.webui.native_folder_picker import NativeFolderPickerError, pick_native_file

            if self._closed or self._picker_lock.locked():
                raise RemoteError("file_picker_unavailable")
            # The route is authenticated and loopback-only. No caller-provided
            # command, file content or initial directory enters the OS dialog.
            async with self._picker_lock:
                try:
                    return {"path": await pick_native_file()}
                except NativeFolderPickerError:
                    raise RemoteError("file_picker_unavailable") from None
        if action == "discover":
            from nanobot.webui.ssh_config import discover_hosts

            config_file = payload.get("ssh_config", "")
            if not isinstance(config_file, str):
                raise RemoteError("invalid_profile")
            discovery = await asyncio.to_thread(discover_hosts, config_file)
            return dict(discovery)
        async with self._lock:
            if self._closed:
                raise RemoteError("local_io_error")
            profiles = self._read()
            key = str(payload.get("id", ""))
            if action == "pair_start":
                return_origin = payload.get("return_origin", "")
                if not isinstance(return_origin, str):
                    raise RemoteError("pair_invalid")
                return self.pairing.start(return_origin)
            if action == "pair_cancel":
                self.pairing.cancel(key)
                return {"cancelled": True}
            if action in {"pair_preview", "pair_finish"}:
                code = payload.get("code", "")
                if not isinstance(code, str):
                    raise RemoteError("pair_invalid")
                receipt = self.pairing.saved_receipt(profiles[key].pair_id) if action == "pair_finish" and key in profiles and profiles[key].pair_id else None
                if receipt is None:
                    receipt = self.pairing.review(key, code)
                matches = [saved_key for saved_key, saved in profiles.items()
                           if saved.pair_id and (previous := self.pairing.saved_receipt(saved.pair_id))
                           and previous.destination() == receipt.destination()]
                # Prefer an already-open connection; never disconnect it merely
                # because the user paired this same instance again.
                live_key = next((saved_key for saved_key in matches
                                 if (live := self.connections.get(saved_key))
                                 and live.tunnel.active and not live.error), "")
                if action == "pair_finish" and live_key:
                    await self._check(self.connections[live_key])
                    if self.connections[live_key].error:
                        live_key = ""
                if action == "pair_preview":
                    preview = receipt.preview()
                    if matches:
                        preview["existing_connection"] = {"id": live_key or matches[0],
                                                          "name": profiles[matches[0]].name,
                                                          "connected": bool(live_key)}
                    return preview
                if len(profiles) >= 20 and key not in profiles:
                    raise RemoteError("profile_limit")
                # Completion is idempotent. No browser-provided host/path/key is
                # trusted as a substitute for the encrypted server receipt.
                if key in profiles:
                    return {"id": live_key or key, **self.snapshot()}
                receipt = self.pairing.finish(key, code)
                profile = self.pairing.profile(receipt)
                if matches:
                    profile.name = profiles[matches[0]].name
                    # A saved route belongs to this exact verified destination.
                    # Keep it when re-pairing; do not fall back to a broken VPN route.
                    source = profiles[live_key or matches[-1]]
                    if source.ssh_config:
                        route = self.pairing.path(key) / "ssh_route"
                        _write_text_atomic(route, Path(source.ssh_config).read_text())
                        route.chmod(0o600)
                        profile.ssh_config = str(route)
                known = self._known_hosts(key)
                known.parent.mkdir(parents=True, exist_ok=True)
                _write_text_atomic(known, "nanobot-remote " + receipt.host_key + "\n")
                known.chmod(0o600)
                profiles[key] = _SavedProfile(**profile.model_dump(), pair_id=key)
                self._write(profiles)
                return {"id": live_key or key, **self.snapshot()}
            if action == "save":
                profile = RemoteProfile.model_validate(payload.get("profile"))
                if key and key not in profiles:
                    raise RemoteError("profile_not_found")
                if key and profiles[key].pair_id:
                    raise RemoteError("pair_managed")
                if key and profiles[key].model_dump(include=set(RemoteProfile.model_fields)) == profile.model_dump():
                    # Retrying a slow browser load must not count as editing a
                    # live SSH connection. Real changes still require disconnect.
                    return {"id": key, **self.snapshot()}
                if not key:
                    destination = profile.model_dump(exclude={"name"})
                    for saved_key, saved in profiles.items():
                        if saved.model_dump(include=set(destination)) == destination:
                            # Reopening Add after a failed attempt should reuse
                            # its entry, without renaming it or closing live views.
                            return {"id": saved_key, **self.snapshot()}
                if not key and len(profiles) >= 20:
                    raise RemoteError("profile_limit")
                key = key or str(uuid.uuid4())
                connection = self.connections.get(key)
                if connection:
                    if connection.tunnel.active and not connection.error:
                        raise RemoteError("disconnect_before_edit")
                    # A fresh tab offers Edit for an offline profile. Release its
                    # failed tunnel here instead of demanding a hidden Disconnect.
                    await connection.proxy.pause()
                    del self.connections[key]
                target_changed = key in profiles and any(
                    getattr(profiles[key], field) != getattr(profile, field)
                    for field in ("host", "port", "ssh_config")
                )
                instance_changed = target_changed or (key in profiles and any(
                    getattr(profiles[key], field) != getattr(profile, field)
                    for field in ("config_path", "runtime_user", "identity_file")
                ))
                if instance_changed:
                    self._remember_origins(profiles)
                # Update editable fields without reconstructing (and losing)
                # managed origin metadata for an unchanged destination.
                profiles[key] = (profiles[key].model_copy(update=profile.model_dump())
                                 if key in profiles and not instance_changed
                                 else _SavedProfile(**profile.model_dump()))
                self._write(profiles)
                if instance_changed:
                    self._compatibility.pop(key, None)
                if target_changed:
                    self._known_hosts(key).unlink(missing_ok=True)
                    self._unverified.pop(key, None)
                    self._unknown_hosts.discard(key)
                return {"id": key, **self.snapshot()}
            if key not in profiles:
                raise RemoteError("profile_not_found")
            if action == "rename":
                name = payload.get("name")
                if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 64
                        or any(ord(char) < 32 or ord(char) == 127 for char in name)):
                    raise RemoteError("invalid_name")
                # Display metadata only: preserve live tunnels, origins and
                # credentials. All verified grants for this instance share a name.
                receipt = self.pairing.saved_receipt(profiles[key].pair_id) if profiles[key].pair_id else None
                for saved_key, saved in profiles.items():
                    if saved_key == key or (receipt and saved.pair_id
                            and (other := self.pairing.saved_receipt(saved.pair_id))
                            and other.destination() == receipt.destination()):
                        saved.name = name.strip()
                self._write(profiles)
                return self.snapshot()
            if action == "pair_route":
                profile = profiles[key]
                if not profile.pair_id:
                    raise RemoteError("pair_invalid")
                existing = self.connections.get(key)
                if existing and existing.tunnel.active and not existing.error:
                    raise RemoteError("disconnect_before_edit")
                route_id = str(payload.get("route_id", ""))
                if route_id:
                    source = profiles.get(route_id)
                    if source is None or source.pair_id:
                        raise RemoteError("profile_not_found")
                    config = await remote_ssh.pairing_route(source, profile.host.split("@")[-1])
                    path = self.pairing.path(profile.pair_id) / "ssh_route"
                    _write_text_atomic(path, config)
                    path.chmod(0o600)
                    profile.ssh_config = str(path)
                else:
                    profile.ssh_config = ""
                self._write(profiles)
                return self.snapshot()
            if action in {"connect", "inspect"}:
                try:
                    if action == "inspect":
                        if profiles[key].pair_id:
                            raise RemoteError("pair_managed")
                        from nanobot.webui.remote_discovery import inspect

                        return await inspect(profiles[key], self._known_hosts(key))
                    return await self._connect(key, profiles[key])
                except RemoteError as exc:
                    if str(exc) == "host_key_unknown":
                        self._unknown_hosts.add(key)
                    else:
                        self._unknown_hosts.discard(key)
                    raise
            if action == "fingerprint":
                if key not in self._unknown_hosts or self._known_hosts(key).exists():
                    raise RemoteError("host_key_changed")
                known_host, fingerprint = await remote_ssh.scan_host_key(profiles[key])
                challenge = secrets.token_urlsafe(24)
                self._unverified[key] = (challenge, known_host, time.monotonic() + 300)
                return {"fingerprint": fingerprint, "challenge": challenge}
            if action == "trust":
                pending = self._unverified.pop(key, None)
                if (not pending or pending[2] < time.monotonic()
                        or not secrets.compare_digest(pending[0], str(payload.get("challenge", "")))
                        or key not in self._unknown_hosts or self._known_hosts(key).exists()):
                    raise RemoteError("host_key_changed")
                path = self._known_hosts(key)
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_text_atomic(path, pending[1])
                path.chmod(0o600)
                self._unknown_hosts.discard(key)
                return {"trusted": True}
            if action in {"disconnect", "remove"}:
                pair_id = profiles[key].pair_id
                if action == "remove":
                    self._remember_origins(profiles)
                    del profiles[key]
                    # Commit the directory before destroying its credentials.
                    # A failed save must leave the listed connection usable.
                    self._write(profiles)
                connection = self.connections.pop(key, None)
                if connection:
                    await connection.proxy.pause()
                if action == "remove":
                    self._compatibility.pop(key, None)
                    if pair_id:
                        self.pairing.forget(pair_id)
                    self._known_hosts(key).unlink(missing_ok=True)
                    self._unknown_hosts.discard(key)
                    self._unverified.pop(key, None)
                return self.snapshot()
            raise RemoteError("unknown_action")

    def _launch(self, key: str, profile: RemoteProfile, connection: Connection) -> dict[str, Any]:
        return {"id": key, "name": profile.name, "host": profile.host,
                "hostname": connection.hostname, "config_path": connection.config_path,
                "url": f"{connection.proxy.origin}/#/?bootstrapSecret={quote(connection.proxy.secret, safe='')}",
                "gateway_id": connection.gateway_id, "view_id": self._view_session}

    async def _connect(self, key: str, profile: _SavedProfile) -> dict[str, Any]:
        existing = self.connections.get(key)
        if existing:
            await self._check(existing)
            if not existing.error:
                return self._launch(key, profile, existing)
            await existing.proxy.pause()
            del self.connections[key]
        if len(self.connections) >= 4:
            raise RemoteError("connection_limit")
        self._compatibility.pop(key, None)
        known_hosts = self._known_hosts(key)
        transport: RemoteProfile = profile
        if profile.pair_id:
            data = self.pairing.connection(profile.pair_id)
            transport = remote_ssh.PairedSSHProfile(**profile.model_dump(include=set(RemoteProfile.model_fields)))
        else:
            data = await remote_ssh.probe(profile, known_hosts)
        used_ports = self._remember_origins(self._read())
        # Retire browser origins from the earlier transparent tunnel. Those
        # origins may still contain remote secrets in old tabs/localStorage.
        # Retire origins that previously executed remote-provided JS, including
        # persistent service workers. They cannot intercept this local client.
        local_port = profile.local_port if profile.proxy_origin and profile.local_client_origin else 0
        proxy = self._proxies.get(local_port)
        if proxy is not None:
            tunnel = proxy.tunnel
            tunnel.resume(transport, data["port"], known_hosts)
        else:
            tunnel = await remote_ssh.open_tunnel(
                transport, data["port"], known_hosts, excluded_ports=used_ports,
            )
        base = f"http://127.0.0.1:{tunnel.port}"
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
                response = await client.get(
                    f"{base}/webui/terminal", headers={"X-Nanobot-Auth": data["secret"]},
                )
                if response.status_code in {401, 403}:
                    raise RemoteError("remote_auth_failed")
                if response.status_code != 200:
                    raise RemoteError("incompatible_gateway")
                raw_identity = response.json()
                if not isinstance(raw_identity, dict):
                    raise RemoteError("incompatible_gateway")
                identity = cast(dict[str, Any], raw_identity)
                if (type(identity.get("protocolVersion")) is not int or identity.get("protocolVersion") != 1
                        or not isinstance(identity.get("gatewayId"), str)):
                    raise RemoteError("incompatible_gateway")
                if identity["gatewayId"] == self.local_gateway_id:
                    raise RemoteError("same_instance")
                # SSH aliases identify routes, not nanobot instances. Don't open
                # two independent browser views of the same live gateway.
                duplicates = [(saved_key, item) for saved_key, item in self.connections.items()
                              if item.gateway_id == identity["gatewayId"]]
                for _, item in duplicates:
                    await self._check(item)
                if any(not item.error for _, item in duplicates):
                    raise RemoteError("duplicate_instance")
                # The host supplies data only. Its frontend need not be installed.
                report = assess_webui_contract(identity.get("webui"))
                self._compatibility[key] = report
                if error := compatibility_error(report):
                    raise RemoteError(error)
            issue_path = data.get("token_issue_path", "")
            if not isinstance(issue_path, str):
                raise RemoteError("incompatible_gateway")
            if proxy is None:
                proxy = await RemoteProxy.open(
                    tunnel, data["secret"], identity["gatewayId"], issue_path,
                    local_port=local_port, excluded_ports=used_ports,
                )
            else:
                proxy.resume(data["secret"], identity["gatewayId"], issue_path)
            connection = Connection(
                tunnel, data["secret"], str(data.get("hostname", profile.host)),
                str(data.get("config_path", profile.config_path)), identity["gatewayId"], proxy,
                paired=bool(profile.pair_id),
            )
            profiles = self._read()
            self._remember_origins(profiles, proxy.port)
            profiles[key].local_port = proxy.port
            profiles[key].proxy_origin = True
            profiles[key].local_client_origin = True
            self._write(profiles)
            # A failed route must not block a newly verified route to this bot.
            # Retire it only after the replacement is saved; retain its profile
            # and browser origin, so other tabs keep their drafts and fail closed.
            for saved_key, item in duplicates:
                await item.proxy.pause()
                del self.connections[saved_key]
            self._proxies[proxy.port] = proxy
            self.connections[key] = connection
            return self._launch(key, profile, connection)
        except BaseException as exc:
            if proxy is not None and proxy.port in self._proxies:
                await proxy.pause()
            else:
                # No launch URL has been returned for this new origin. All
                # internal HTTP requests have finished; retaining it would leak
                # a listener on every failed attempt with local_port still zero.
                if proxy is not None:
                    await proxy.close()
                else:
                    await tunnel.close()
            if isinstance(exc, httpx.HTTPError):
                if profile.pair_id and tunnel.error == "ssh_auth_failed":
                    raise RemoteError("pair_authorization_rejected") from None
                raise RemoteError(tunnel.error or "remote_unreachable") from None
            if isinstance(exc, ValueError):
                raise RemoteError("incompatible_gateway") from None
            raise

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            proxies, self._proxies = self._proxies, {}
            self.connections.clear()
            await asyncio.gather(*(proxy.close() for proxy in proxies.values()))
