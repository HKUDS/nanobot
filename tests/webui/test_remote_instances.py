"""Connection boundaries: no deployment, copied model keys or remote shutdown."""

import asyncio
import json
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import ValidationError
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.webui import remote_instances, remote_ssh
from nanobot.webui.client_contract import webui_contract
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.remote_instances import RemoteInstances
from nanobot.webui.remote_proxy import RemoteProxy
from nanobot.webui.remote_ssh import (
    RemoteError,
    RemoteProfile,
    open_tunnel,
    ssh_arguments,
    ssh_error,
)


@pytest.fixture
def manager(tmp_path):
    return RemoteInstances(tmp_path)


async def save(manager, **values):
    result = await manager.action("save", {"profile": {"name": "Team", "host": "ubuntu@example.test", **values}})
    return result["id"]


@pytest.fixture
def ssh(monkeypatch):
    tunnel = SimpleNamespace(active=True, error="", port=23455, pause=AsyncMock(), close=AsyncMock(), resume=MagicMock())
    proxy = SimpleNamespace(tunnel=tunnel, port=23456, origin="http://127.0.0.1:23456",
                            secret="local-capability", pause=tunnel.pause, close=tunnel.close,
                            resume=MagicMock())
    monkeypatch.setattr(RemoteProxy, "open", AsyncMock(return_value=proxy))
    probe = AsyncMock(return_value={"port": 8765, "secret": "private-webui-secret", "hostname": "team-host"})
    monkeypatch.setattr(remote_ssh, "probe", probe)
    monkeypatch.setattr(remote_ssh, "open_tunnel", AsyncMock(return_value=tunnel))
    state = {"status": 200, "identity": {"protocolVersion": 1, "gatewayId": "remote-one", "webui": webui_contract()}}

    def respond(request):
        if request.url.path == "/webui/terminal":
            assert request.headers["X-Nanobot-Auth"] == "private-webui-secret"
            return httpx.Response(state["status"], json=state["identity"])
        raise AssertionError(f"A data-only host must not be asked for a frontend: {request.url.path}")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    return SimpleNamespace(tunnel=tunnel, proxy=proxy, probe=probe, state=state, client=real_client)


async def test_save_survives_restart_without_credentials(manager):
    key = await save(manager)
    assert RemoteInstances(manager.path.parent).snapshot()["profiles"][0]["id"] == key
    assert "secret" not in manager.path.read_text()
    with pytest.raises(ValidationError):
        await save(manager, private_key="must-never-save")


@pytest.mark.parametrize("contract,code", [
    (None, "webui_compatibility_unknown"),
    ({**webui_contract(), "min_protocol": 2, "max_protocol": 2}, "client_update_required"),
    ({**webui_contract(), "capabilities": []}, "host_update_required"),
])
async def test_contract_failure_keeps_profile_and_reports_correct_update_target(manager, ssh, contract, code):
    key = await save(manager)
    ssh.state["identity"]["webui"] = contract
    with pytest.raises(RemoteError, match=code):
        await manager.action("connect", {"id": key})
    RemoteProxy.open.assert_not_awaited()
    ssh.tunnel.close.assert_awaited_once()
    snapshot = manager.snapshot()
    assert len(snapshot["profiles"]) == 1
    assert snapshot["profiles"][0]["connection_error"] == code
    assert not snapshot["profiles"][0]["connected"]
    assert snapshot["profiles"][0]["compatibility"]["status"] != "compatible"
    assert not manager.connections


async def test_server_upgrade_rechecks_compatibility_without_new_pairing(manager, ssh):
    key = await save(manager)
    ssh.state["identity"].pop("webui")
    with pytest.raises(RemoteError, match="webui_compatibility_unknown"):
        await manager.action("connect", {"id": key})
    saved = manager.path.read_text(encoding="utf-8")
    ssh.state["identity"]["webui"] = {**webui_contract(), "version": "9.0.0"}
    await manager.action("connect", {"id": key})
    assert manager.snapshot()["profiles"][0]["compatibility"]["status"] == "compatible"
    # The stable saved host remains; only its reserved local origin is added.
    assert set(json.loads(manager.path.read_text(encoding="utf-8"))) == set(json.loads(saved))


async def test_host_contract_change_invalidates_live_proxy(manager, ssh):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    ssh.state["identity"]["webui"] = {**webui_contract(), "capabilities": []}
    await manager.health()
    ssh.proxy.pause.assert_awaited_once()
    assert manager.snapshot()["profiles"][0]["connection_error"] == "host_update_required"


async def test_new_local_manager_has_new_view_identity_for_same_remote(manager, ssh):
    key = await save(manager)
    first = await manager.action("connect", {"id": key})
    await manager.action("disconnect", {"id": key})
    resumed = await manager.action("connect", {"id": key})
    assert resumed["view_id"] == first["view_id"]
    restarted = RemoteInstances(manager.path.parent)
    second = await restarted.action("connect", {"id": key})
    assert second["gateway_id"] == first["gateway_id"]
    assert second["view_id"] != first["view_id"]
    assert restarted.snapshot()["profiles"][0]["view_id"] == second["view_id"]
    assert "view_id" not in manager.path.read_text()


async def test_rename_connected_profile_only_changes_display_name(manager, ssh):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    before = json.loads(manager.path.read_text(encoding="utf-8"))
    live = manager.connections[key]
    result = await manager.action("rename", {"id": key, "name": "  腾讯云 nanobot  "})
    assert result["profiles"][0]["name"] == "腾讯云 nanobot"
    assert result["profiles"][0]["connected"] is True
    before[key]["name"] = "腾讯云 nanobot"
    assert json.loads(manager.path.read_text(encoding="utf-8")) == before
    assert RemoteInstances(manager.path.parent).snapshot()["profiles"][0]["name"] == "腾讯云 nanobot"
    assert manager.connections[key] is live
    ssh.tunnel.pause.assert_not_awaited()
    ssh.tunnel.close.assert_not_awaited()
    assert ssh.probe.await_count == 1


@pytest.mark.parametrize("name", [None, 7, {}, "", "   ", "a" * 65, "a\nb", "a\x00b", "a\x7fb"])
async def test_rename_invalid_name_does_not_change_saved_profile(manager, name):
    key = await save(manager)
    before = manager.path.read_bytes()
    with pytest.raises(RemoteError, match="invalid_name"):
        await manager.action("rename", {"id": key, "name": name})
    assert manager.path.read_bytes() == before


async def test_rename_validates_id_and_does_not_merge_matching_names(manager):
    first = await save(manager)
    second = await save(manager, host="other-host")
    await manager.action("rename", {"id": first, "name": "x" * 64})
    assert manager._read()[second].name == "Team"
    with pytest.raises(RemoteError, match="profile_not_found"):
        await manager.action("rename", {"id": "missing", "name": "Team"})


async def test_unchanged_save_allows_retry_after_browser_load_failure(manager, ssh):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    before = manager.path.read_bytes()
    result = await manager.action("save", {"id": key, "profile": {
        "name": "Team", "host": "ubuntu@example.test",
    }})
    assert result["id"] == key
    assert manager.path.read_bytes() == before
    ssh.tunnel.pause.assert_not_awaited()


async def test_readding_exact_destination_reuses_entry_without_renaming_or_disconnect(manager, ssh):
    key = await save(manager)
    before = manager.path.read_bytes()
    assert await save(manager, name="Another name") == key
    assert manager.path.read_bytes() == before
    await manager.action("connect", {"id": key})
    before = manager.path.read_bytes()
    live = manager.connections[key]
    assert await save(manager, name="Still the same instance") == key
    assert manager.path.read_bytes() == before
    assert manager.connections[key] is live
    ssh.tunnel.pause.assert_not_awaited()
    ssh.tunnel.close.assert_not_awaited()


@pytest.mark.parametrize("change", [
    {"host": "another-alias"}, {"port": 2222}, {"identity_file": "/other/key"},
    {"runtime_user": "nanobot"}, {"ssh_config": "/other/config"},
    {"config_path": "/srv/another-bot/config.json"},
])
async def test_different_destinations_are_not_collapsed_before_connecting(manager, change):
    first = await save(manager)
    assert await save(manager, **change) != first
    assert len(manager.snapshot()["profiles"]) == 2


@pytest.mark.parametrize("host", ["-oProxyCommand=evil", "user@host;whoami", "a\nb", "$(id)", "host name"])
def test_hosts_cannot_be_shell_or_ssh_options(host):
    with pytest.raises(ValidationError):
        RemoteProfile(name="Team", host=host)


def test_strict_ssh_without_agent_forwarding(monkeypatch):
    monkeypatch.setattr(remote_ssh.shutil, "which", lambda _: "/usr/bin/ssh")
    args = ssh_arguments(RemoteProfile(name="Team", host="my-alias"))
    for option in ["StrictHostKeyChecking=yes", "BatchMode=yes", "ForwardAgent=no", "ControlPath=none", "PermitLocalCommand=no", "ExitOnForwardFailure=yes", "RemoteCommand=none"]:
        assert option in args
    assert "StrictHostKeyChecking=no" not in args


async def test_connect_checks_protocol_and_only_disconnects_tunnel(manager, ssh):
    key = await save(manager)
    connection = await manager.action("connect", {"id": key})
    assert connection["hostname"] == "team-host"
    assert connection["gateway_id"] == "remote-one"
    assert connection["url"].startswith("http://127.0.0.1:23456/#/?bootstrapSecret=")
    assert "private-webui-secret" not in json.dumps(connection)
    assert "private-webui-secret" not in json.dumps(manager.snapshot())
    assert "private-webui-secret" not in manager.path.read_text()
    await manager.action("disconnect", {"id": key})
    ssh.tunnel.pause.assert_awaited_once()
    ssh.tunnel.close.assert_not_awaited()
    assert not manager.snapshot()["profiles"][0]["connected"]
    assert len(manager.snapshot()["profiles"]) == 1


@pytest.mark.parametrize(("status", "identity", "error"), [
    (401, {}, "remote_auth_failed"), (404, {}, "incompatible_gateway"),
    (200, {"protocolVersion": 2, "gatewayId": "other"}, "incompatible_gateway"),
    (200, {"protocolVersion": 1}, "incompatible_gateway"),
])
async def test_bad_target_closes_tunnel_and_never_returns_launch_url(manager, ssh, status, identity, error):
    key = await save(manager)
    ssh.state.update(status=status, identity=identity)
    with pytest.raises(RemoteError, match=error):
        await manager.action("connect", {"id": key})
    ssh.tunnel.close.assert_awaited_once()
    assert not manager.connections


async def test_failed_initial_retries_do_not_accumulate_listeners(manager, ssh, monkeypatch):
    monkeypatch.setattr(remote_ssh.shutil, "which", lambda _: "fixture-ssh")
    monkeypatch.setattr(remote_ssh, "open_tunnel", AsyncMock(wraps=open_tunnel))
    key = await save(manager)
    ssh.state["status"] = 404
    for _ in range(8):
        with pytest.raises(RemoteError, match="incompatible_gateway"):
            await manager.action("connect", {"id": key})
        assert not manager._proxies
        assert json.loads(manager.path.read_text())[key]["local_port"] == 0


async def test_failed_reconnect_retains_published_origin(manager, ssh):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    await manager.action("disconnect", {"id": key})
    ssh.state["status"] = 404
    with pytest.raises(RemoteError, match="incompatible_gateway"):
        await manager.action("connect", {"id": key})
    assert manager._proxies == {23456: ssh.proxy}
    ssh.tunnel.close.assert_not_awaited()


@pytest.mark.parametrize("paired", [False, True])
async def test_rejected_pair_key_explains_repair_not_ssh_agent(manager, ssh, monkeypatch, paired):
    key = await save(manager)
    if paired:
        profiles = manager._read()
        profiles[key].pair_id = key
        manager._write(profiles)
        monkeypatch.setattr(manager.pairing, "connection", lambda _: ssh.probe.return_value)
    ssh.tunnel.error = "ssh_auth_failed"

    def reject(_):
        raise httpx.ReadError("SSH authentication rejected")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: ssh.client(
        transport=httpx.MockTransport(reject), **kwargs,
    ))
    with pytest.raises(RemoteError, match="pair_authorization_rejected" if paired else "ssh_auth_failed"):
        await manager.action("connect", {"id": key})
    assert not manager.connections
    ssh.tunnel.close.assert_awaited_once()


async def test_server_restart_requires_reconnect_not_local_fallback(manager, ssh):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    ssh.state["identity"]["gatewayId"] = "restarted"
    profile = (await manager.health())["profiles"][0]
    assert not profile["connected"]
    assert profile["connection_error"] == "instance_changed"
    assert profile["gateway_id"] == "remote-one"
    assert key in manager.connections
    ssh.tunnel.close.assert_not_awaited()


@pytest.mark.parametrize(("status", "identity", "error"), [
    (401, {}, "remote_auth_failed"),
    (403, {}, "remote_auth_failed"),
    (200, {"protocolVersion": 2, "gatewayId": "remote-one"}, "incompatible_gateway"),
    (200, {"protocolVersion": True, "gatewayId": "remote-one"}, "incompatible_gateway"),
    (200, [], "incompatible_gateway"),
])
async def test_health_reports_actionable_safe_errors(manager, ssh, status, identity, error):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    ssh.state.update(status=status, identity=identity)
    profile = (await manager.health())["profiles"][0]
    assert profile["connection_error"] == error
    assert not profile["connected"]
    assert "private-webui-secret" not in json.dumps(profile)


async def test_explicit_disconnect_is_not_a_network_failure(manager, ssh):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    await manager.action("disconnect", {"id": key})
    assert (await manager.health())["profiles"][0]["connection_error"] == "disconnected"
    await manager.action("connect", {"id": key})
    profile = (await manager.health())["profiles"][0]
    assert profile["connected"]
    assert not profile.get("connection_error")


async def test_connect_to_own_gateway_is_rejected_without_nesting(manager, ssh):
    manager.local_gateway_id = "remote-one"
    key = await save(manager)
    with pytest.raises(RemoteError, match="same_instance"):
        await manager.action("connect", {"id": key})
    ssh.tunnel.close.assert_awaited_once()
    assert not manager.connections


@pytest.mark.parametrize("gateway_id", ["remote-one", "another-instance"])
async def test_aliases_cannot_open_duplicate_views_but_distinct_instances_can(manager, ssh, monkeypatch, gateway_id):
    first = await save(manager)
    await manager.action("connect", {"id": first})
    first_connection = manager.connections[first]
    alias = await save(manager, host="another-alias", config_path="/srv/bot/config.json")
    # A genuinely separate tunnel/proxy, rather than the shared fixture handle.
    second_tunnel = SimpleNamespace(active=True, error="", port=23457, close=AsyncMock())
    second_proxy = SimpleNamespace(port=23458, origin="http://127.0.0.1:23458", secret="local-two")
    monkeypatch.setattr(remote_ssh, "open_tunnel", AsyncMock(return_value=second_tunnel))
    monkeypatch.setattr(RemoteProxy, "open", AsyncMock(return_value=second_proxy))
    ssh.state["identity"]["gatewayId"] = gateway_id
    if gateway_id == "remote-one":
        with pytest.raises(RemoteError, match="duplicate_instance"):
            await manager.action("connect", {"id": alias})
        second_tunnel.close.assert_awaited_once()
        RemoteProxy.open.assert_not_awaited()
        assert alias not in manager.connections
    else:
        assert (await manager.action("connect", {"id": alias}))["gateway_id"] == gateway_id
        second_tunnel.close.assert_not_awaited()
    assert manager.connections[first] is first_connection
    ssh.tunnel.pause.assert_not_awaited()
    ssh.tunnel.close.assert_not_awaited()


async def test_forget_only_removes_saved_profile(manager, ssh):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    await manager.action("remove", {"id": key})
    assert manager.snapshot()["profiles"] == []
    ssh.tunnel.pause.assert_awaited_once()
    ssh.tunnel.close.assert_not_awaited()


async def test_offline_alias_does_not_block_replacement_connection(manager, ssh, monkeypatch):
    first = await save(manager)
    await manager.action("connect", {"id": first})
    ssh.tunnel.active = False
    alias = await save(manager, host="working-route")
    second_tunnel = SimpleNamespace(active=True, error="", port=23457, close=AsyncMock())
    second_proxy = SimpleNamespace(port=23458, origin="http://127.0.0.1:23458", secret="local-two")
    monkeypatch.setattr(remote_ssh, "open_tunnel", AsyncMock(return_value=second_tunnel))
    monkeypatch.setattr(RemoteProxy, "open", AsyncMock(return_value=second_proxy))

    assert (await manager.action("connect", {"id": alias}))["gateway_id"] == "remote-one"
    assert first not in manager.connections
    assert manager.connections[alias].proxy is second_proxy
    ssh.tunnel.pause.assert_awaited_once()
    ssh.tunnel.close.assert_not_awaited()  # Keep the old browser origin reserved.
    assert len(manager.snapshot()["profiles"]) == 2  # No saved routes/drafts were deleted.


async def test_closing_local_manager_reaps_ssh(manager, ssh):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    await manager.close()
    ssh.tunnel.close.assert_awaited_once()
    assert len(manager.snapshot()["profiles"]) == 1


async def test_refresh_reuses_a_healthy_tunnel(manager, ssh):
    key = await save(manager)
    first = await manager.action("connect", {"id": key})
    second = await manager.action("connect", {"id": key})
    assert first["url"] == second["url"]
    ssh.probe.assert_awaited_once()
    ssh.tunnel.close.assert_not_awaited()


async def test_reconnect_resumes_reserved_listener(manager, ssh):
    key = await save(manager)
    first = await manager.action("connect", {"id": key})
    await manager.action("disconnect", {"id": key})
    second = await manager.action("connect", {"id": key})
    assert first["url"] == second["url"]
    remote_ssh.open_tunnel.assert_awaited_once()
    ssh.tunnel.resume.assert_called_once()
    ssh.tunnel.close.assert_not_awaited()


async def test_shutdown_does_not_release_origin_during_health_request(manager, ssh, monkeypatch):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(request):
        entered.set()
        await release.wait()
        ssh.tunnel.close.assert_not_awaited()
        assert request.headers["X-Nanobot-Auth"] == "private-webui-secret"
        return httpx.Response(200, json=ssh.state["identity"])

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: ssh.client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    health = asyncio.create_task(manager.health())
    await asyncio.wait_for(entered.wait(), 2)
    shutdown = asyncio.create_task(manager.close())
    try:
        await asyncio.sleep(0)
        assert not shutdown.done()
        ssh.tunnel.close.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(health, shutdown)
    ssh.tunnel.close.assert_awaited_once()


async def test_health_deadline_returns_editable_offline_directory(manager, ssh, monkeypatch):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    cancelled = asyncio.Event()

    async def respond(request):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(remote_instances, "_HEALTH_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: ssh.client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    directory = await asyncio.wait_for(manager.health(), 1)
    assert not directory["profiles"][0]["connected"]
    assert cancelled.is_set()
    await manager.action("save", {"id": key, "profile": {
        "name": "Repaired", "host": "ubuntu@example.test",
    }})
    assert manager.snapshot()["profiles"][0]["name"] == "Repaired"


async def test_health_budget_includes_waiting_for_connection_lock(manager, ssh, monkeypatch):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    monkeypatch.setattr(remote_instances, "_HEALTH_TIMEOUT_SECONDS", 0.02)
    async with manager._lock:
        directory = await asyncio.wait_for(manager.health(), 1)
    assert directory["profiles"][0]["id"] == key


async def test_reconnect_keeps_origin_and_changing_target_does_not(manager, ssh):
    key = await save(manager)
    first = await manager.action("connect", {"id": key})
    assert json.loads(manager.path.read_text())[key]["local_port"] == 23456
    await manager.action("disconnect", {"id": key})
    await manager.action("save", {"id": key, "profile": {"name": "Renamed", "host": "ubuntu@example.test"}})
    assert json.loads(manager.path.read_text())[key]["local_port"] == 23456
    # Editing display metadata must preserve the local-client origin marker,
    # not just its port: otherwise reconnect silently retires that origin.
    assert json.loads(manager.path.read_text())[key]["local_client_origin"] is True
    second = await manager.action("connect", {"id": key})
    assert second["url"] == first["url"]
    RemoteProxy.open.assert_awaited_once()
    await manager.action("disconnect", {"id": key})
    await manager.action("save", {"id": key, "profile": {"name": "Other", "host": "other.example.test"}})
    assert json.loads(manager.path.read_text())[key]["local_port"] == 0
    assert "compatibility" not in manager.snapshot()["profiles"][0]


async def test_editing_failed_target_clears_its_compatibility_diagnosis(manager, ssh):
    key = await save(manager)
    ssh.state["identity"].pop("webui")
    with pytest.raises(RemoteError, match="webui_compatibility_unknown"):
        await manager.action("connect", {"id": key})
    result = await manager.action("save", {"id": key, "profile": {
        "name": "Other", "host": "other.example.test",
    }})
    assert result["profiles"][0]["connection_error"] == "disconnected"
    assert "compatibility" not in result["profiles"][0]


async def test_corrupt_store_not_overwritten(manager):
    manager.path.write_text("corrupt")
    with pytest.raises(RemoteError, match="profile_store_invalid"):
        await save(manager)
    assert manager.path.read_text() == "corrupt"


@pytest.mark.parametrize("change", [
    {"config_path": "/srv/other-bot/config.json"},
    {"runtime_user": "other-bot"},
    {"identity_file": "/tmp/other-identity"},
])
async def test_changing_instance_drops_origin_but_keeps_server_trust(manager, ssh, change):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    await manager.action("disconnect", {"id": key})
    known_hosts = manager.path.parent / "remote-hosts" / key
    known_hosts.parent.mkdir()
    known_hosts.write_text("nanobot-remote ssh-ed25519 fixture\n")
    await manager.action("save", {"id": key, "profile": {
        "name": "Another bot", "host": "ubuntu@example.test", **change,
    }})
    assert json.loads(manager.path.read_text())[key]["local_port"] == 0
    assert known_hosts.read_text() == "nanobot-remote ssh-ed25519 fixture\n"


@pytest.mark.parametrize("failure", ["process-exit", "health-error"])
async def test_offline_profile_can_be_edited_without_hidden_disconnect(manager, ssh, failure):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    if failure == "process-exit":
        ssh.tunnel.active = False
    else:
        ssh.state["status"] = 503
    assert not (await manager.health())["profiles"][0]["connected"]
    await manager.action("save", {"id": key, "profile": {"name": "Fixed", "host": "fixed.example.test"}})
    ssh.tunnel.pause.assert_awaited_once()
    assert key not in manager.connections
    assert manager.snapshot()["profiles"][0]["host"] == "fixed.example.test"


async def test_live_profile_still_requires_explicit_disconnect_before_edit(manager, ssh):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    with pytest.raises(RemoteError, match="disconnect_before_edit"):
        await manager.action("save", {"id": key, "profile": {"name": "Changed", "host": "other.test"}})
    ssh.tunnel.close.assert_not_awaited()


async def test_retired_origins_survive_edit_forget_and_restart(manager, ssh, monkeypatch):
    key = await save(manager)
    await manager.action("connect", {"id": key})
    await manager.action("disconnect", {"id": key})
    await manager.action("save", {"id": key, "profile": {
        "name": "Other instance", "host": "ubuntu@example.test", "config_path": "/srv/b/config.json",
    }})
    restarted = RemoteInstances(manager.path.parent)

    async def different_origin(*args, local_port, excluded_ports):
        assert local_port == 0
        assert 23456 in excluded_ports
        ssh.proxy.port = 23457
        return ssh.proxy

    monkeypatch.setattr(RemoteProxy, "open", different_origin)
    await restarted.action("connect", {"id": key})
    await restarted.action("remove", {"id": key})
    assert restarted.snapshot()["profiles"] == []
    restarted_again = RemoteInstances(manager.path.parent)
    assert restarted_again._remember_origins({}) == {23456, 23457}
    assert "private-webui-secret" not in (manager.path.parent / "remote-origin-ports.json").read_text()


async def test_old_profile_origin_is_remembered_before_first_edit(manager, ssh):
    key = await save(manager)
    old = json.loads(manager.path.read_text())
    old[key]["local_port"] = 23456
    manager.path.write_text(json.dumps(old))  # Pre-ledger profile created by the previous build.
    await manager.action("save", {"id": key, "profile": {
        "name": "Other", "host": "ubuntu@example.test", "runtime_user": "other-user",
    }})
    assert RemoteInstances(manager.path.parent)._remember_origins({}) == {23456}


@pytest.mark.parametrize("proxy_origin", [False, True])
async def test_legacy_transparent_or_remote_code_origin_is_not_reused(manager, ssh, proxy_origin):
    key = await save(manager)
    old = json.loads(manager.path.read_text())
    old[key]["local_port"] = 12345
    old[key]["proxy_origin"] = proxy_origin
    manager.path.write_text(json.dumps(old))
    await manager.action("connect", {"id": key})
    kwargs = RemoteProxy.open.call_args.kwargs
    assert kwargs["local_port"] == 0
    assert 12345 in kwargs["excluded_ports"]
    assert json.loads(manager.path.read_text())[key]["proxy_origin"] is True
    assert json.loads(manager.path.read_text())[key]["local_client_origin"] is True
    assert "proxy_origin" not in manager.snapshot()["profiles"][0]


async def test_invalid_origin_ledger_blocks_target_change_without_losing_profile_or_pin(manager):
    key = await save(manager)
    before = manager.path.read_bytes()
    ledger = manager.path.parent / "remote-origin-ports.json"
    ledger.write_text('{"corrupt": true}')
    known_hosts = manager.path.parent / "remote-hosts" / key
    known_hosts.parent.mkdir()
    known_hosts.write_text("trusted-key")
    with pytest.raises(RemoteError, match="profile_store_invalid"):
        await manager.action("save", {"id": key, "profile": {"name": "Other", "host": "other.example.test"}})
    assert manager.path.read_bytes() == before
    assert known_hosts.read_text() == "trusted-key"


async def test_new_host_trust_is_explicit_scoped_and_one_use(manager, ssh, monkeypatch):
    key = await save(manager)
    ssh.probe.side_effect = RemoteError("host_key_unknown")
    with pytest.raises(RemoteError):
        await manager.action("connect", {"id": key})
    monkeypatch.setattr(remote_ssh, "scan_host_key", AsyncMock(return_value=("nanobot-remote ssh-ed25519 test-key\n", "SHA256:test")))
    result = await manager.action("fingerprint", {"id": key})
    assert result["fingerprint"] == "SHA256:test"
    assert not list(manager.path.parent.glob("remote-hosts/*"))
    await manager.action("trust", {"id": key, "challenge": result["challenge"]})
    assert (manager.path.parent / "remote-hosts" / key).read_text() == "nanobot-remote ssh-ed25519 test-key\n"
    with pytest.raises(RemoteError, match="host_key_changed"):
        await manager.action("trust", {"id": key, "challenge": result["challenge"]})
    with pytest.raises(RemoteError, match="host_key_changed"):
        await manager.action("fingerprint", {"id": key})


async def test_changed_known_host_cannot_be_overridden_in_ui(manager, ssh):
    key = await save(manager)
    ssh.probe.side_effect = RemoteError("host_key_changed")
    with pytest.raises(RemoteError, match="host_key_changed"):
        await manager.action("connect", {"id": key})
    with pytest.raises(RemoteError, match="host_key_changed"):
        await manager.action("fingerprint", {"id": key})


async def test_shutdown_prevents_new_tunnels(manager, ssh):
    key = await save(manager)
    await manager.close()
    with pytest.raises(RemoteError, match="local_io_error"):
        await manager.action("connect", {"id": key})
    ssh.probe.assert_not_awaited()


@pytest.mark.parametrize(("stderr", "code"), [
    (b"WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED", "host_key_changed"),
    (b"Host key verification failed", "host_key_unknown"),
    (b"Permission denied (publickey). secret-information", "ssh_auth_failed"),
    (b"timed out with private address", "ssh_unreachable"),
    (b"sudo: permission denied for private-user", "runtime_user_denied"),
    (b"WARNING: UNPROTECTED PRIVATE KEY FILE! Permission denied", "ssh_key_permissions"),
    (b"sign_and_send_pubkey: signing failed for /private/path: agent refused operation\nPermission denied", "ssh_agent_refused"),
    (b"/private/config: Bad configuration option: typo", "ssh_config_invalid"),
    (b"channel 0: open failed: administratively prohibited: open failed", "ssh_forwarding_denied"),
    (b"channel 0: open failed: connect failed: Connection refused", "remote_unreachable"),
])
def test_errors_never_echo_raw_ssh_output(stderr, code):
    assert ssh_error(stderr) == code


@pytest.fixture
def gateway(tmp_path):
    return build_gateway_services(
        config=WebSocketConfig(host="127.0.0.1", token_issue_secret="synthetic-access-secret"),
        bus=MagicMock(), session_manager=None,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )


@pytest.mark.parametrize("action", ["save", "discover", "inspect", "pick_file", "connect", "remove", "trust"])
async def test_http_mutations_are_not_gettable_even_with_token(gateway, action):
    request = Request(f"/api/remote-instances/{action}", Headers())
    connection = SimpleNamespace(remote_address=("127.0.0.1", 10000))
    result = await gateway.http.dispatch(connection, request)
    assert result.status_code == 405


@pytest.mark.parametrize("path", ["/local/ssh-config", None])
async def test_file_picker_returns_path_without_saving_profile(manager, monkeypatch, path):
    from nanobot.webui import native_file_picker

    choose = AsyncMock(return_value=path)
    monkeypatch.setattr(native_file_picker, "pick_native_file", choose)
    assert await manager.action("pick_file", {}) == {"path": path}
    assert not manager.path.exists()
    choose.assert_awaited_once_with()


async def test_file_picker_failure_does_not_expose_native_error(manager, monkeypatch):
    from nanobot.webui import native_file_picker

    monkeypatch.setattr(native_file_picker, "pick_native_file", AsyncMock(
        side_effect=native_file_picker.NativeFilePickerError("private diagnostic"),
    ))
    with pytest.raises(RemoteError, match="^file_picker_unavailable$"):
        await manager.action("pick_file", {})


async def test_file_picker_does_not_open_multiple_system_dialogs(manager, monkeypatch):
    from nanobot.webui import native_file_picker

    choose = AsyncMock()
    monkeypatch.setattr(native_file_picker, "pick_native_file", choose)
    async with manager._picker_lock:
        with pytest.raises(RemoteError, match="file_picker_unavailable"):
            await manager.action("pick_file", {})
    choose.assert_not_awaited()


@pytest.mark.parametrize("peer,host,origin", [
    ("203.0.113.1", "127.0.0.1:8765", "http://127.0.0.1:8765"),
    ("127.0.0.1", "bot.example.com", "https://bot.example.com"),
    ("127.0.0.1", "127.0.0.1:8765", "https://evil.example"),
])
async def test_remote_clients_cannot_open_local_file_picker(gateway, monkeypatch, peer, host, origin):
    from nanobot.webui import native_file_picker

    choose = AsyncMock()
    monkeypatch.setattr(native_file_picker, "pick_native_file", choose)
    connection = SimpleNamespace(remote_address=(peer, 10000), request=SimpleNamespace(
        headers=Headers({"Host": host, "Origin": origin}),
    ))
    result = await gateway.http.dispatch_webui_mutation(connection, "remote.pick_file", {})
    assert result.status_code == 403
    choose.assert_not_awaited()


@pytest.mark.parametrize(("peer", "host", "origin", "status"), [
    ("127.0.0.1", "127.0.0.1:8765", "http://127.0.0.1:8765", 200),
    ("203.0.113.1", "127.0.0.1:8765", "http://127.0.0.1:8765", 403),
    ("127.0.0.1", "bot.example.com", "https://bot.example.com", 403),
    ("127.0.0.1", "127.0.0.1:8765", "https://evil.example", 403),
])
async def test_ssh_access_is_local_and_authenticated(gateway, peer, host, origin, status):
    token = gateway.tokens.issue_api_token(60)
    connection = SimpleNamespace(remote_address=(peer, 10000))
    request = Request("/api/remote-instances", Headers({"Host": host, "Origin": origin, "Authorization": f"Bearer {token}"}))
    result = await gateway.http.dispatch(connection, request)
    assert result.status_code == status
    request = Request("/api/remote-instances", Headers({"Host": host}))
    assert (await gateway.http.dispatch(connection, request)).status_code == 401


async def test_cancellation_reaps_inflight_probe(monkeypatch):
    process = MagicMock(returncode=None)
    process.communicate = AsyncMock(side_effect=asyncio.CancelledError)
    process.wait = AsyncMock(return_value=0)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(asyncio.CancelledError):
        await remote_ssh.probe(RemoteProfile(name="Test", host="example.test"))
    process.terminate.assert_called_once()


@pytest.mark.parametrize("field", ["trustedProxyAuth", "trusted_proxy_auth"])
def test_ssh_probe_rejects_trusted_assertion_bypass(tmp_path, field):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"channels": {"websocket": {
        "enabled": True, "tokenIssueSecret": "synthetic-root",
        field: {"assertionHeader": "Host", "trustedPeers": ["127.0.0.0/8"]},
    }}}))
    result = subprocess.run([sys.executable, "-c", remote_ssh._PROBE, str(path)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout.split("NANOBOT_REMOTE:")[1]) == {"error": "incompatible_gateway"}


@pytest.mark.parametrize("banner", [b"", b"Welcome to the server\n", b"{\"port\": 1}\nWelcome without newline"])
async def test_probe_ignores_shell_banners_without_exposing_them(monkeypatch, banner):
    data = {"port": 8765, "secret": "synthetic-root"}
    process = MagicMock(returncode=0)
    process.communicate = AsyncMock(return_value=(
        banner + b"\n" + remote_ssh._PROBE_PREFIX + json.dumps(data).encode() + b"\nGoodbye\n", b"",
    ))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    assert await remote_ssh.probe(RemoteProfile(name="Test", host="example.test")) == data


@pytest.mark.parametrize("output", [
    b"Welcome. Password required for private-user.",
    b'\x1eNANOBOT_REMOTE:{"port": 8765, "secret": "s"}\n\x1eNANOBOT_REMOTE:{}',
    b"\x1eNANOBOT_REMOTE:not-json-with-private-data",
])
async def test_invalid_probe_protocol_is_not_reported_as_bad_config(monkeypatch, output):
    process = MagicMock(returncode=0)
    process.communicate = AsyncMock(return_value=(output, b""))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(RemoteError, match="^probe_failed$"):
        await remote_ssh.probe(RemoteProfile(name="Test", host="example.test"))


@pytest.mark.parametrize("config", ["invalid JSON", "[]", '{"channels": null}', '{"channels": {"websocket": []}}'])
def test_probe_reports_malformed_config_as_config_error(tmp_path, config):
    path = tmp_path / "config.json"
    path.write_text(config)
    result = subprocess.run([sys.executable, "-c", remote_ssh._PROBE, str(path)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout.split("NANOBOT_REMOTE:")[1]) == {"error": "config_invalid"}


async def test_tunnel_refuses_an_existing_listener(monkeypatch):
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with pytest.raises(RemoteError, match="local_port_in_use"):
            await remote_ssh.open_tunnel(
                RemoteProfile(name="Test", host="example.test"), 8765,
                local_port=listener.getsockname()[1],
            )
    spawn.assert_not_awaited()


@pytest.mark.skipif(hasattr(socket, "SO_EXCLUSIVEADDRUSE"), reason="Unix TIME_WAIT reuse; Windows requires exclusive ownership")
async def test_tunnel_reuses_closed_port_with_time_wait():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1) as peer:
            accepted, _ = listener.accept()
            accepted.close()  # Server-side active close leaves TIME_WAIT after peer closes.
            assert peer.recv(1) == b""
    tunnel = await remote_ssh.open_tunnel(
        RemoteProfile(name="Test", host="example.test"), 8765, local_port=port,
    )
    assert tunnel.port == port
    await tunnel.close()
