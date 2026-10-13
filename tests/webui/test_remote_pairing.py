"""Pairing protocol, restricted authorization and local API regression tests."""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nanobot.webui import remote_pair_server, remote_pairing, remote_ssh
from nanobot.webui.remote_instances import RemoteInstances
from nanobot.webui.remote_pairing import PairReceipt, PairStore, read_request, seal
from nanobot.webui.remote_ssh import (
    PairedSSHProfile,
    RemoteError,
    ssh_arguments,
    transport_arguments,
)


def ssh_public():
    return Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()


def receipt(request, **updates):
    return PairReceipt(**dict(id=request.id, ssh_key=request.ssh_key, host="203.0.113.1", user="ubuntu",
                             ssh_port=22, host_key=ssh_public(), hostname="team", config_path="/srv/nanobot/config.json",
                             port=8765, secret="private-webui-credential", authorized_until=int(time.time()) + 86400,
                             **updates))


@pytest.fixture
def pair(tmp_path):
    store = PairStore(tmp_path)
    start = store.start()
    request = read_request(start["command"].split()[-1])
    value = receipt(request)
    return store, start, request, value, seal(request, value)


def test_round_trip_only_preview_public_fields_and_restart(pair):
    store, start, request, value, code = pair
    assert "secret" not in json.dumps(start)
    assert "private-webui-credential" not in code
    preview = store.preview(request.id, code)
    assert preview["host"] == "ubuntu@203.0.113.1"
    assert "secret" not in json.dumps(preview)
    store.finish(request.id, code)
    assert PairStore(store.root.parent).connection(request.id)["secret"] == value.secret
    assert store.finish(request.id, code) == value
    if os.name != "nt":
        for path in store.path(request.id).iterdir():
            assert path.stat().st_mode & 0o777 == 0o600
        assert store.path(request.id).stat().st_mode & 0o777 == 0o700
    assert value.secret not in (store.path(request.id) / "receipt").read_text()


def test_expiry_and_reconnect_have_distinct_lifetimes(pair, monkeypatch):
    store, _, request, _, code = pair
    store.finish(request.id, code)
    monkeypatch.setattr(remote_pairing.time, "time", lambda: request.expires + 1)
    with pytest.raises(RemoteError, match="pair_expired"):
        store.preview(request.id, code)
    assert store.connection(request.id)["secret"]


def test_wrong_request_and_tampering_fail_closed(pair):
    store, _, request, _, code = pair
    another = store.start()
    for invalid in [code[:-20] + "AAAAAAAAAAAAAAAAAAAA", "garbage", "nbpc1." + "A" * 32769]:
        with pytest.raises(RemoteError, match="pair_invalid"):
            store.preview(request.id, invalid)
    with pytest.raises(RemoteError, match="pair_invalid"):
        store.preview(another["id"], code)
    assert not (store.path(request.id) / "receipt").exists()


def test_wrapped_console_code_is_accepted(pair):
    store, _, request, _, code = pair
    wrapped = "\n".join(code[i:i + 80] for i in range(0, len(code), 80))
    assert store.preview(request.id, wrapped)["id"] == request.id


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8870", "http://localhost:5173", "http://[::1]:8765"])
def test_return_link_is_loopback_fragment_only_and_survives_new_store(tmp_path, origin):
    from urllib.parse import urlsplit

    store = PairStore(tmp_path)
    started = store.start(origin)
    request = read_request(started["command"].split()[-1])
    value = receipt(request)
    code = seal(request, value)
    link = remote_pairing.return_link(request, code)
    assert link == origin + "/#/remote?pairing=" + code
    assert not urlsplit(link).query
    assert "private-webui-credential" not in link
    assert PairStore(tmp_path).preview(request.id, code)["host"] == "ubuntu@203.0.113.1"


@pytest.mark.parametrize("origin", ["https://example.com", "http://127.0.0.1.evil.test", "http://127.0.0.1@evil.test", "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://127.0.0.1/path", "http://127.0.0.1?redirect=bad", "http://127.0.0.1#bad", "http://127.0.0.1\n", "http://2130706433", "file:///tmp"])
def test_return_link_rejects_external_or_ambiguous_targets_before_creating_key(tmp_path, origin):
    store = PairStore(tmp_path)
    with pytest.raises(RemoteError, match="pair_invalid"):
        store.start(origin)
    assert not store.root.exists()


def test_legacy_request_still_has_copy_code_fallback(pair):
    _, _, request, _, code = pair
    assert remote_pairing.return_link(request, code) == ""


def test_cancel_only_deletes_pending_pair_files(pair):
    store, _, request, _, code = pair
    pending = store.start()
    store.cancel(pending["id"])
    assert not store.path(pending["id"]).exists()
    store.finish(request.id, code)
    store.cancel(request.id)
    assert store.connection(request.id)["secret"]
    with pytest.raises(RemoteError):
        store.cancel("../../outside")


@pytest.mark.skipif(sys.platform == "win32", reason="Linux server authorization uses POSIX ownership and flock")
def test_server_appends_restricted_key_and_revoke_preserves_existing(pair, tmp_path):
    _, _, request, _, _ = pair
    home = tmp_path / "server-home"
    home.mkdir()
    (home / ".ssh").mkdir(mode=0o700)
    original = ssh_public() + " existing-admin\n"
    keys = home / ".ssh/authorized_keys"
    keys.write_text(original)
    remote_pair_server.write_authorization(home, request, 8765, int(time.time()) + 86400)
    lines = keys.read_text().splitlines()
    assert lines[0] + "\n" == original
    assert lines[1].startswith('restrict,expiry-time="')
    assert "port-forwarding" not in lines[1]
    assert request.ssh_key in lines[1]
    assert "private-webui" not in (home / ".ssh/nanobot-remote" / request.id / "bridge.py").read_text()
    with pytest.raises(RemoteError, match="pair_used"):
        remote_pair_server.write_authorization(home, request, 8765, int(time.time()) + 86400)
    remote_pair_server.remove_authorization(home, request.id)
    assert keys.read_text() == original
    remote_pair_server.remove_authorization(home, request.id)
    assert keys.read_text() == original


@pytest.mark.skipif(sys.platform == "win32", reason="Linux server authorization uses POSIX ownership and flock")
def test_server_refuses_symlink_authorized_keys_without_touching_target(pair, tmp_path):
    _, _, request, _, _ = pair
    home = tmp_path / "server"
    (home / ".ssh").mkdir(parents=True, mode=0o700)
    outside = tmp_path / "important"
    outside.write_text("untouched")
    (home / ".ssh/authorized_keys").symlink_to(outside)
    with pytest.raises(OSError):
        remote_pair_server.write_authorization(home, request, 8765, int(time.time()) + 86400)
    assert outside.read_text() == "untouched"


def test_paired_transport_cannot_fall_back_to_generic_probe_or_forwarding(pair, monkeypatch):
    store, _, request, value, _ = pair
    monkeypatch.setattr(remote_ssh.shutil, "which", lambda _: "/usr/bin/ssh")
    profile = PairedSSHProfile(**store.profile(value).model_dump())
    args = ssh_arguments(profile)
    assert "IdentityAgent=none" in args and "IdentitiesOnly=yes" in args
    assert args[1:3] == ["-F", os.devnull]
    transport = transport_arguments(profile, value.port, store.path(request.id) / "known_hosts")
    assert "-W" not in transport
    assert transport[-1] == "nanobot-remote-bridge-v2"
    assert "sudo" not in " ".join(transport)


@pytest.mark.parametrize("command", ["echo MUST-NOT-EXECUTE", "nanobot-remote-bridge-v2"])
def test_fixed_bridge_streams_only_to_baked_in_loopback_port(tmp_path, command):
    # Real bidirectional bytes, no SSH_ORIGINAL_COMMAND interpolation.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    def serve():
        with listener:
            connection, _ = listener.accept()
            with connection:
                data = bytearray()
                while chunk := connection.recv(8192):
                    data.extend(chunk)
                connection.sendall(b"received:" + data)
    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    target = tmp_path / ".ssh" / "nanobot-remote" / "device"
    target.mkdir(parents=True)
    line = "restrict fixture-key nanobot-remote:device\n"
    (target / "authorization").write_text(line)
    (tmp_path / ".ssh" / "authorized_keys").write_text(line)
    bridge = target / "bridge.py"
    bridge.write_text(remote_pair_server.bridge_source(port, int(time.time()) + 60))
    result = subprocess.run([sys.executable, "-I", "-S", str(bridge)],
                            input=b"hello-webui", capture_output=True, timeout=5,
                            env={**os.environ, "SSH_ORIGINAL_COMMAND": command})
    worker.join(2)
    assert result.returncode == 0
    prefix = remote_ssh._BRIDGE_READY if command == "nanobot-remote-bridge-v2" else b""
    assert result.stdout == prefix + b"received:hello-webui"


@pytest.mark.parametrize("reason", ["expired", "revoked", "missing", "another-device"])
def test_guarded_bridge_rejects_new_channels_without_connecting(tmp_path, reason):
    target = tmp_path / ".ssh" / "nanobot-remote" / "device"
    target.mkdir(parents=True)
    line = "restrict fixture-key nanobot-remote:device\n"
    (target / "authorization").write_text(line)
    keys = tmp_path / ".ssh" / "authorized_keys"
    keys.write_text(line if reason == "expired" else line.replace(":device", ":other") if reason == "another-device" else "")
    if reason == "missing":
        keys.unlink()
    bridge = target / "bridge.py"
    bridge.write_text(remote_pair_server.bridge_source(1, int(time.time()) + (-1 if reason == "expired" else 60)))
    result = subprocess.run([sys.executable, "-I", "-S", str(bridge)], capture_output=True, timeout=5,
                            env={**os.environ, "SSH_ORIGINAL_COMMAND": "nanobot-remote-bridge-v2"})
    assert result.returncode == 1
    assert not result.stdout  # No reuse capability or connection to the target.
    assert b"Permission denied" in result.stderr


async def test_api_pair_finalization_pins_host_and_hides_credentials(tmp_path):
    manager = RemoteInstances(tmp_path)
    started = await manager.action("pair_start", {})
    request = read_request(started["command"].split()[-1])
    value = receipt(request)
    code = seal(request, value)
    preview = await manager.action("pair_preview", {"id": request.id, "code": code})
    assert "secret" not in preview
    result = await manager.action("pair_finish", {"id": request.id, "code": code})
    assert result["profiles"][0]["paired"] is True
    assert "private-webui" not in json.dumps(result)
    assert "private-webui" not in manager.path.read_text()
    assert manager._known_hosts(request.id).read_text() == "nanobot-remote " + value.host_key + "\n"
    again = await manager.action("pair_finish", {"id": request.id, "code": code})
    assert again["id"] == request.id and len(again["profiles"]) == 1
    with pytest.raises(RemoteError, match="pair_managed"):
        await manager.action("save", {"id": request.id, "profile": manager.pairing.profile(value).model_dump()})
    await manager.action("pair_cancel", {"id": request.id})
    assert manager.pairing.connection(request.id)["secret"]
    await manager.action("remove", {"id": request.id})
    assert not manager.pairing.path(request.id).exists()
    assert manager.snapshot()["profiles"] == []


async def test_failed_forget_preserves_saved_pair_for_restart_and_retry(tmp_path, monkeypatch):
    manager = RemoteInstances(tmp_path)
    request = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    value = receipt(request)
    await manager.action("pair_finish", {"id": request.id, "code": seal(request, value)})
    directory_before = manager.path.read_bytes()
    identity_path = manager.pairing.path(request.id) / "identity"
    identity_before = identity_path.read_bytes()

    def fail_save(_profiles):
        raise OSError("disk full")

    monkeypatch.setattr(manager, "_write", fail_save)
    with pytest.raises(OSError, match="disk full"):
        await manager.action("remove", {"id": request.id})

    restarted = RemoteInstances(tmp_path)
    assert restarted.path.read_bytes() == directory_before
    assert restarted.snapshot()["profiles"][0]["id"] == request.id
    assert identity_path.read_bytes() == identity_before
    assert restarted.pairing.connection(request.id)["secret"] == value.secret
    assert restarted._known_hosts(request.id).exists()
    await restarted.action("rename", {"id": request.id, "name": "Still usable"})
    await restarted.action("remove", {"id": request.id})
    assert restarted.snapshot()["profiles"] == []
    assert not identity_path.exists()


async def test_repeated_pairing_groups_one_instance_without_deleting_authorizations(tmp_path):
    manager = RemoteInstances(tmp_path)
    first = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    original = receipt(first)
    await manager.action("pair_finish", {"id": first.id, "code": seal(first, original)})
    profiles = manager._read()
    profiles[first.id].name = "My team"
    manager._write(profiles)
    before = manager.pairing.path(first.id).joinpath("identity").read_bytes()
    second = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    renewed = original.model_copy(update={"id": second.id, "ssh_key": second.ssh_key})
    code = seal(second, renewed)
    preview = await manager.action("pair_preview", {"id": second.id, "code": code})
    assert preview["existing_connection"] == {"id": first.id, "name": "My team", "connected": False}
    assert len(manager.snapshot()["profiles"]) == 1  # Preview never saves or deletes.
    result = await manager.action("pair_finish", {"id": second.id, "code": code})
    assert result["id"] == second.id
    assert len(result["profiles"]) == 2  # Grants remain separately manageable.
    assert {item["instance_id"] for item in result["profiles"]} == {first.id}
    assert {item["name"] for item in result["profiles"]} == {"My team"}
    assert manager.pairing.path(first.id).joinpath("identity").read_bytes() == before
    assert manager.pairing.connection(second.id)["secret"] == original.secret
    assert original.secret not in json.dumps(result)
    assert original.host_key not in json.dumps(result)
    assert (await manager.action("pair_finish", {"id": second.id, "code": code}))["id"] == second.id
    assert len({item["instance_id"] for item in RemoteInstances(tmp_path).snapshot()["profiles"]}) == 1
    await manager.action("remove", {"id": second.id})
    assert manager.pairing.path(first.id).joinpath("identity").read_bytes() == before
    assert len(manager.snapshot()["profiles"]) == 1


@pytest.mark.parametrize("change", [
    {"host": "203.0.113.2"}, {"user": "other"}, {"ssh_port": 2222},
    {"config_path": "/srv/other/config.json"}, {"port": 9876},
    {"secret": "another-private-credential"}, {"token_issue_path": "/different-issuer"},
    {"host_key": ssh_public()},
])
async def test_same_name_or_ip_never_groups_different_pairing_destinations(tmp_path, change):
    manager = RemoteInstances(tmp_path)
    first = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    original = receipt(first)
    await manager.action("pair_finish", {"id": first.id, "code": seal(first, original)})
    second = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    other = original.model_copy(update={"id": second.id, "ssh_key": second.ssh_key, **change})
    code = seal(second, other)
    preview = await manager.action("pair_preview", {"id": second.id, "code": code})
    assert "existing_connection" not in preview
    result = await manager.action("pair_finish", {"id": second.id, "code": code})
    assert len({item["instance_id"] for item in result["profiles"]}) == 2


async def test_rename_paired_instance_updates_only_verified_sibling_grants(tmp_path):
    manager = RemoteInstances(tmp_path)
    first = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    original = receipt(first)
    await manager.action("pair_finish", {"id": first.id, "code": seal(first, original)})
    requests = [first]
    for path in [original.config_path, "/srv/different/config.json"]:
        request = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
        value = original.model_copy(update={"id": request.id, "ssh_key": request.ssh_key, "config_path": path})
        await manager.action("pair_finish", {"id": request.id, "code": seal(request, value)})
        requests.append(request)
    before = manager._read()
    receipts = {item.id: manager.pairing.path(item.id).joinpath("receipt").read_bytes() for item in requests}
    live = SimpleNamespace(tunnel=SimpleNamespace(active=True), error="", gateway_id="live-session",
                           proxy=SimpleNamespace(pause=AsyncMock()))
    manager.connections[first.id] = live
    result = await manager.action("rename", {"id": requests[1].id, "name": "My cloud"})
    assert [p["name"] for p in result["profiles"]] == ["My cloud", "My cloud", original.hostname]
    for item in requests:
        assert manager.pairing.path(item.id).joinpath("receipt").read_bytes() == receipts[item.id]
        assert manager._read()[item.id].model_dump(exclude={"name"}) == before[item.id].model_dump(exclude={"name"})
    live.proxy.pause.assert_not_awaited()


@pytest.mark.parametrize("healthy", [True, False])
async def test_repair_retains_route_and_reuses_only_a_healthy_existing_connection(tmp_path, monkeypatch, healthy):
    manager = RemoteInstances(tmp_path)
    first = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    original = receipt(first)
    await manager.action("pair_finish", {"id": first.id, "code": seal(first, original)})
    route = manager.pairing.path(first.id) / "ssh_route"
    route.write_text("Host *\n  ProxyCommand /usr/bin/nc -b en0 %h %p\n")
    profiles = manager._read()
    profiles[first.id].ssh_config = str(route)
    profiles[first.id].local_port = 23456
    manager._write(profiles)
    live = SimpleNamespace(tunnel=SimpleNamespace(active=True), error="", gateway_id="live-session",
                           proxy=SimpleNamespace(pause=AsyncMock()))
    manager.connections[first.id] = live

    async def check(connection):
        connection.error = "" if healthy else "remote_auth_failed"

    monkeypatch.setattr(manager, "_check", check)
    second = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    renewed = original.model_copy(update={"id": second.id, "ssh_key": second.ssh_key})
    code = seal(second, renewed)
    result = await manager.action("pair_finish", {"id": second.id, "code": code})
    assert result["id"] == (first.id if healthy else second.id)
    assert manager.connections[first.id] is live
    live.proxy.pause.assert_not_awaited()
    assert manager._read()[first.id].local_port == 23456
    new_route = manager.pairing.path(second.id) / "ssh_route"
    assert new_route.read_text() == route.read_text()
    if os.name != "nt":
        assert new_route.stat().st_mode & 0o777 == 0o600
    assert manager._read()[second.id].ssh_config == str(new_route)


async def test_grouping_old_receipts_is_read_only_and_tolerates_expired_or_missing_grants(tmp_path, monkeypatch):
    manager = RemoteInstances(tmp_path)
    first = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    original = receipt(first)
    await manager.action("pair_finish", {"id": first.id, "code": seal(first, original)})
    second = read_request((await manager.action("pair_start", {}))["command"].split()[-1])
    other = original.model_copy(update={"id": second.id, "ssh_key": second.ssh_key})
    await manager.action("pair_finish", {"id": second.id, "code": seal(second, other)})
    saved = manager.path.read_bytes()
    monkeypatch.setattr(time, "time", lambda: original.authorized_until + 10)
    assert len({item["instance_id"] for item in manager.snapshot()["profiles"]}) == 1
    assert manager.path.read_bytes() == saved
    with pytest.raises(RemoteError, match="pair_authorization_expired"):
        manager.pairing.connection(first.id)
    manager.pairing.path(second.id).joinpath("receipt").unlink()
    result = manager.snapshot()["profiles"]
    assert len(result) == 2
    assert "instance_id" not in result[1]
    assert manager.path.read_bytes() == saved


@pytest.mark.parametrize("with_route", [False, True])
async def test_paired_profile_follows_moved_data_root(tmp_path, monkeypatch, with_route):
    original = tmp_path / "original"
    manager = RemoteInstances(original)
    started = await manager.action("pair_start", {})
    request = read_request(started["command"].split()[-1])
    value = receipt(request)
    await manager.action("pair_finish", {"id": request.id, "code": seal(request, value)})
    external = tmp_path / "external-ssh-config"
    external.write_text("Host alias\n    HostName 203.0.113.1\n")
    source = await manager.action("save", {"profile": {
        "name": "Existing route", "host": "alias", "ssh_config": str(external),
    }})
    if with_route:
        monkeypatch.setattr(remote_ssh, "pairing_route", AsyncMock(return_value="Host *\n"))
        await manager.action("pair_route", {"id": request.id, "route_id": source["id"]})
    await manager.close()
    moved = tmp_path / "renamed-data-root"
    shutil.move(str(original), moved)
    restarted = RemoteInstances(moved)
    profiles = (await restarted.health())["profiles"]
    paired = next(item for item in profiles if item["id"] == request.id)
    assert paired["identity_file"] == str(restarted.pairing.path(request.id) / "identity")
    assert paired["ssh_config"] == (str(restarted.pairing.path(request.id) / "ssh_route") if with_route else "")
    assert next(item for item in profiles if item["id"] == source["id"])["ssh_config"] == str(external)

    async def check_transport(profile, port, known_hosts, **kwargs):
        assert profile.identity_file == paired["identity_file"]
        assert profile.ssh_config == paired["ssh_config"]
        args = ssh_arguments(profile, known_hosts)
        assert str(original) not in " ".join(args)
        assert known_hosts.read_text() == "nanobot-remote " + value.host_key + "\n"
        raise RemoteError("ssh_unreachable")

    monkeypatch.setattr(remote_ssh, "open_tunnel", check_transport)
    monkeypatch.setattr(remote_ssh.shutil, "which", lambda _: "/usr/bin/ssh")
    with pytest.raises(RemoteError, match="ssh_unreachable"):
        await restarted.action("connect", {"id": request.id})
    await restarted.action("remove", {"id": request.id})
    assert not restarted.pairing.path(request.id).exists()
    assert external.exists()
    assert len(RemoteInstances(moved).snapshot()["profiles"]) == 1


def test_model_keys_never_enter_pairing_metadata(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"providers": {"deepseek": {"apiKey": "not-exported"}},
                                "channels": {"websocket": {"enabled": True, "tokenIssueSecret": "webui-only"}}}))
    assert "not-exported" not in json.dumps(remote_pair_server.metadata(path))


def test_pairing_modules_can_import_without_posix_server_dependencies():
    # Windows clients still exercise encryption, import, reconnect and metadata.
    # Only the Linux server grant/revoke path may require fcntl or pwd.
    script = """
import sys
sys.modules['fcntl'] = None
sys.modules['pwd'] = None
from nanobot.webui import remote_pair_server, remote_pairing
from nanobot.cli import remote
assert remote_pair_server.metadata
assert remote_pairing.PairStore
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()


async def test_route_import_only_copies_network_options(monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.write_text("")
    process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(
        b"hostname 203.0.113.1\nuser ubuntu\nport 22\nidentityfile /private/admin-key\nproxycommand nc -b en0 %h %p\nbindaddress none\nbindinterface none\nproxyjump none\n", b"")))
    monkeypatch.setattr(remote_ssh.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(remote_ssh, "stop_process", AsyncMock())
    profile = remote_ssh.RemoteProfile(name="existing", host="alias", ssh_config=str(config))
    route = await remote_ssh.pairing_route(profile, "203.0.113.1")
    assert route == "Host *\n    proxycommand nc -b en0 %h %p\n"
    assert "identity" not in route and "admin" not in route
    with pytest.raises(RemoteError, match="pair_route_mismatch"):
        await remote_ssh.pairing_route(profile, "different.example")


def test_request_cannot_inject_authorized_keys_options(pair):
    _, start, _, _, _ = pair
    raw = remote_pairing.unpack("nbpr1.", start["command"].split()[-1])
    raw["ssh_key"] = 'command="sh" ' + raw["ssh_key"]
    with pytest.raises(RemoteError, match="pair_invalid"):
        read_request(remote_pairing.pack("nbpr1.", raw))


def test_expired_device_cannot_connect(pair, monkeypatch):
    store, _, request, value, code = pair
    store.finish(request.id, code)
    monkeypatch.setattr(remote_pairing.time, "time", lambda: value.authorized_until + 1)
    with pytest.raises(RemoteError, match="pair_authorization_expired"):
        store.connection(request.id)
    # The UI can explain expiry without opening a path around connection().
    assert store.authorization_until(request.id) == value.authorized_until


def test_authorization_expiry_does_not_hide_other_profiles_on_corrupt_receipt(pair):
    store, _, request, _, code = pair
    store.finish(request.id, code)
    (store.path(request.id) / "receipt").write_text("invalid")
    assert store.authorization_until(request.id) is None
    with pytest.raises(RemoteError, match="pair_invalid"):
        store.connection(request.id)


async def test_saved_pair_exposes_only_expiry_and_public_metadata(pair, monkeypatch):
    store, _, request, value, code = pair
    manager = RemoteInstances(store.root.parent)
    await manager.action("pair_finish", {"id": request.id, "code": code})
    monkeypatch.setattr(remote_pairing.time, "time", lambda: value.authorized_until + 1)
    profile = manager.snapshot()["profiles"][0]
    assert profile["authorized_until"] == value.authorized_until
    assert value.secret not in json.dumps(profile)
    assert "receipt" not in profile and "exchange_key" not in profile
    with pytest.raises(RemoteError, match="pair_authorization_expired"):
        await manager.action("connect", {"id": request.id})


def test_failure_before_authorizing_does_not_write_keys(pair, monkeypatch, tmp_path):
    _, _, request, value, _ = pair
    install = AsyncMock()
    monkeypatch.setattr(remote_pair_server, "as_account", install)
    with pytest.raises(RemoteError):
        remote_pair_server.authorize(request, host=value.host, user=value.user, ssh_port=22,
                                    config=tmp_path / "missing", host_key=value.host_key,
                                    until=value.authorized_until)
    install.assert_not_called()
