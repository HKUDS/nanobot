from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from websockets.datastructures import Headers

from nanobot.integrations.credentials import CredentialStore, PrivateStoreError, icloud_credentials
from nanobot.webui.integrations_api import IntegrationsSettingsHandler
from nanobot.webui.settings_services import WebUISettingsServices
from tests.webui.test_settings_routes import _mutation_request, _router

SECRET = "test-only-password-do-not-log"


@pytest.fixture
def handler(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"agents": {"defaults": {"workspace": str(workspace)}}}))
    monkeypatch.setattr("nanobot.webui.integrations_api.memory_status", lambda c: {
        "enabled": False, "rerank_mode": "shadow", "items": None, "status": "disabled"})
    monkeypatch.setattr("nanobot.webui.integrations_api.service_status", lambda w: [])
    return IntegrationsSettingsHandler(WebUISettingsServices.create(config))


def account(id="work", **overrides):
    return {"id": id, "email": "user@example.org", "host": "imap.example.org", "port": 993,
            "username": "user@example.org", "allowed_folders": ["Orders"],
            "rules": [{"name": "orders", "destination": "Orders", "sender_globs": ["*@shop.example"],
                       "subject_contains": []}], **overrides}


def test_status_has_no_side_effects_or_fake_counts(handler):
    config = handler.settings.config.load()
    before = list(config.workspace_path.iterdir())
    result = handler.handle("status", None)
    assert result.status == 200
    assert result.payload["memory"]["items"] is None
    assert result.payload["evolution"]["experiences"] is None
    assert result.payload["exported"] is False
    assert list(config.workspace_path.iterdir()) == before


def test_mail_secret_write_only_private_and_idempotent_account_upsert(handler, caplog):
    result = handler.handle("mail", account(password=SECRET))
    assert result.status == 200
    assert SECRET not in repr(result)
    assert SECRET not in caplog.text
    assert SECRET not in handler.settings.config.path.read_text()
    cfg = handler.settings.config.load()
    reference = cfg.personal_integrations.mail_accounts[0].credential_ref
    store = CredentialStore(cfg.workspace_path)
    assert store.get(reference) == SECRET
    if os.name != "nt":
        assert stat.S_IMODE(store.path(reference).stat().st_mode) == 0o600
        assert stat.S_IMODE(store.path(reference).parent.stat().st_mode) == 0o700
    assert result.payload["mail"]["accounts"][0]["credential_configured"] is True
    assert "credential_ref" not in result.payload["mail"]["accounts"][0]
    assert handler.handle("mail", account(password="")).status == 200
    assert handler.settings.config.load().personal_integrations.mail_accounts[0].credential_ref == reference
    assert handler.handle("mail", account(id="personal", password="other-password")).status == 200
    assert len(handler.settings.config.load().personal_integrations.mail_accounts) == 2


@pytest.mark.parametrize("change", [{"host": "imap.other.org"}, {"username": "another@example.org"}, {"port": 994}])
def test_identity_change_requires_new_password(handler, change):
    handler.handle("mail", account(password=SECRET))
    before = handler.settings.config.path.read_bytes()
    result = handler.handle("mail", account(**change))
    assert result.status == 400
    assert handler.settings.config.path.read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"host": "http://127.0.0.1/"}, {"id": "../../outside"}, {"host": "127.0.0.1"},
    {"host": "internal.local"}, {"host": "--config=evil"}, {"port": 0},
    {"password": {"not": "a string"}}, {"password": "new\nline"},
    {"allowed_folders": ["-flag"]}, {"allowed_folders": ["Orders", "Orders"]},
    {"credential_ref": "a" * 32}, {"credentialRef": "a" * 32},
    {"rules": [{"name": "bad", "destination": "Unapproved", "sender_globs": ["*"]}]},
    {SECRET: SECRET},
])
def test_invalid_config_never_echoes_inputs_or_writes(handler, changes):
    before = handler.settings.config.path.read_bytes()
    result = handler.handle("mail", account(**changes))
    assert result.status == 400
    assert SECRET not in repr(result)
    assert handler.settings.config.path.read_bytes() == before
    assert not (handler.settings.config.load().workspace_path / ".nanobot/integrations/secrets").exists()


def test_icloud_secret_and_existing_secret_preserved(handler, monkeypatch):
    values = {"username": "apple@example.org", "password": SECRET}
    result = handler.handle("icloud", values)
    assert result.status == 200
    assert result.payload["icloud"]["credential_configured"] is True
    assert SECRET not in repr(result)
    assert icloud_credentials(handler.settings.config.path) == ("apple@example.org", SECRET, "https://caldav.icloud.com/")
    result = handler.handle("icloud", {"username": "apple@example.org", "sleep_hours": 9})
    assert result.status == 200
    assert icloud_credentials(handler.settings.config.path)[1] == SECRET
    result = handler.handle("icloud", {"username": "another@example.org"})
    assert result.status == 400


def test_secret_cleaned_up_on_config_save_failure(handler, monkeypatch):
    import nanobot.webui.settings_services as module

    monkeypatch.setattr(module, "save_config", lambda *args: (_ for _ in ()).throw(OSError(SECRET)))
    result = handler.handle("mail", account(password=SECRET))
    assert result.status == 500
    assert SECRET not in repr(result)
    directory = handler.settings.config.load().workspace_path / ".nanobot/integrations/secrets"
    assert not list(directory.iterdir())


def test_export_real_consumer_toml_without_password_and_without_starting(handler, monkeypatch):
    handler.handle("mail", account(password=SECRET))
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("must not start or probe a service"))
    result = handler.handle("prepare", {})
    assert result.status == 200
    assert result.payload["exported"] is True
    config = handler.settings.config.load()
    root = config.workspace_path / ".nanobot/mail"
    worker = tomllib.loads((root / "config.toml").read_text())
    client = tomllib.loads((root / "himalaya.toml").read_text())
    watcher = tomllib.loads((root / "carillon.toml").read_text())
    assert worker["worker"]["dry_run"] is True
    assert worker["accounts"]["work"]["source_mailboxes"] == ["INBOX"]
    assert client["accounts"]["work"]["imap"]["server"] == "imaps://imap.example.org:993"
    command = client["accounts"]["work"]["imap"]["sasl"]["plain"]["password"]["command"]
    assert command[0] == sys.executable
    assert command[1:3] == ["-m", "nanobot.integrations.credentials"]
    assert "enqueue-env" in watcher["accounts"]["work"]["imap"]["hook"]["on-message-added"]["cmd"]
    assert all(SECRET not in p.read_text() for p in root.glob("*.toml"))
    assert handler.handle("prepare", {}).status == 200
    handler.handle("mail", account(password="rotated"))
    assert handler.payload()["exported"] is False
    assert handler.handle("prepare", {}).status == 200


def test_export_preserves_unmanaged_or_manually_changed_config(handler):
    handler.handle("mail", account(password=SECRET))
    workspace = handler.settings.config.load().workspace_path
    root = workspace / ".nanobot/mail"
    root.mkdir(parents=True, mode=0o700)
    target = root / "himalaya.toml"
    target.write_text("# Manually configured, leave intact\n")
    result = handler.handle("prepare", {})
    assert result.status == 400
    assert target.read_text() == "# Manually configured, leave intact\n"
    assert not (root / "config.toml").exists()


def test_partial_export_can_be_retried_without_manual_repair(handler, monkeypatch):
    import nanobot.integrations.export as module

    handler.handle("mail", account(password=SECRET))
    original = module.atomic_private_write
    failed = False

    def fail_once(path, data):
        nonlocal failed
        if path.name == "himalaya.toml" and not failed:
            failed = True
            raise OSError("simulated interruption")
        original(path, data)

    monkeypatch.setattr(module, "atomic_private_write", fail_once)
    assert handler.handle("prepare", {}).status == 500
    assert handler.payload()["exported"] is False
    assert handler.handle("prepare", {}).status == 200
    assert handler.payload()["exported"] is True


def test_icloud_export_keeps_existing_monitor_config_and_trigger(handler):
    handler.handle("icloud", {"username": "apple@example.org", "password": SECRET})
    config = handler.settings.config.load()
    project = config.workspace_path / "projects/icloud-time-manager"
    (project / "time_manager").mkdir(parents=True)
    (project / "time_manager/cli.py").write_text("# installed")
    (project / "data").mkdir(mode=0o700)
    original = 'trigger_id = "trigger-123"\n'
    (project / "data/config.toml").write_text(original)
    result = handler.handle("prepare", {})
    assert result.status == 200
    exported = tomllib.loads((project / "data/webui.toml").read_text())
    assert exported["nanobot_config_path"] == str(handler.settings.config.path)
    assert exported["trigger_id"] == "trigger-123"
    assert exported["auto_manage_sleep"] is False
    assert (project / "data/config.toml").read_text() == original
    assert SECRET not in repr(exported)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink/permission guard")
def test_symlink_and_permission_guards(handler, tmp_path):
    config = handler.settings.config.load()
    outside = tmp_path / "outside"
    outside.mkdir()
    (config.workspace_path / ".nanobot").symlink_to(outside, target_is_directory=True)
    result = handler.handle("mail", account(password=SECRET))
    assert result.status == 400
    assert not list(outside.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_public_secret_file_is_not_read(handler):
    handler.handle("mail", account(password=SECRET))
    config = handler.settings.config.load()
    store = CredentialStore(config.workspace_path)
    ref = config.personal_integrations.mail_accounts[0].credential_ref
    store.path(ref).chmod(0o644)
    with pytest.raises(PrivateStoreError):
        store.get(ref)


@pytest.mark.asyncio
async def test_routes_require_auth_and_mutation_transport(handler):
    path = "/api/settings/integrations/mail"
    for authorized, mutation, expected in [(False, True, 401), (True, False, 405)]:
        router = _router(authorized=authorized, config_path=handler.settings.config.path)
        request = (_mutation_request(path, account(password=SECRET)) if mutation
                   else SimpleNamespace(path=path, headers=Headers()))
        response = await router.dispatch(None, request, path)
        assert response.status_code == expected
        assert SECRET.encode() not in response.body
    router = _router(config_path=handler.settings.config.path)
    request = _mutation_request(path, account(password=SECRET))
    response = await router.dispatch(None, request, path)
    assert response.status_code == 200
    assert SECRET.encode() not in response.body
    read_path = "/api/settings/integrations"
    response = await _router(authorized=False, config_path=handler.settings.config.path).dispatch(
        None, SimpleNamespace(path=read_path, headers=Headers()), read_path)
    assert response.status_code == 401


def test_ws_actions_use_settings_mutation_boundary():
    from nanobot.webui.settings_routes import WebUISettingsRouter
    from nanobot.webui.ws_http import _WEBUI_MUTATION_PATHS

    for action in ("icloud", "mail", "prepare"):
        path = _WEBUI_MUTATION_PATHS[f"settings.integrations.{action}"]
        assert WebUISettingsRouter.is_mutation_path(path)


def test_no_export_for_missing_credentials(handler):
    assert handler.handle("mail", account()).status == 200
    result = handler.handle("prepare", {})
    assert result.status == 400
    assert not (handler.settings.config.load().workspace_path / ".nanobot/mail").exists()


def test_upsert_keeps_order_default_account_and_current_export(handler):
    handler.handle("mail", account(id="work", password=SECRET))
    handler.handle("mail", account(id="personal", password="second-fixture"))
    assert handler.handle("prepare", {}).status == 200
    config = handler.settings.config.load()
    path = config.workspace_path / ".nanobot/mail/himalaya.toml"
    before = path.read_bytes()
    assert handler.handle("mail", account(id="work")).status == 200
    assert [a.id for a in handler.settings.config.load().personal_integrations.mail_accounts] == ["work", "personal"]
    assert handler.payload()["exported"] is True
    assert handler.handle("prepare", {}).status == 200
    assert path.read_bytes() == before
    assert tomllib.loads(before.decode())["accounts"]["work"]["default"] is True


def test_export_detects_editor_change_after_preflight(handler, monkeypatch):
    import nanobot.integrations.export as module

    handler.handle("mail", account(password=SECRET))
    assert handler.handle("prepare", {}).status == 200
    workspace = handler.settings.config.load().workspace_path
    path = workspace / ".nanobot/mail/config.toml"
    original_write = module.atomic_private_write
    edited = False

    def edit_while_recording_intent(target, content):
        nonlocal edited
        if target.name == "export.json" and not edited:
            edited = True
            path.write_text("# changed by operator\n")
        original_write(target, content)

    monkeypatch.setattr(module, "atomic_private_write", edit_while_recording_intent)
    assert handler.handle("prepare", {}).status == 400
    assert path.read_text() == "# changed by operator\n"
    assert handler.payload()["exported"] is False
    assert handler.handle("prepare", {}).status == 400


def test_export_invalidates_on_trigger_and_config_path_change(handler, tmp_path):
    from nanobot.integrations.export import export_current

    handler.handle("icloud", {"username": "apple@example.org", "password": SECRET})
    config = handler.settings.config.load()
    project = config.workspace_path / "projects/icloud-time-manager"
    (project / "time_manager").mkdir(parents=True)
    (project / "time_manager/cli.py").write_text("# installed")
    (project / "data").mkdir(mode=0o700)
    source = project / "data/config.toml"
    source.write_text('trigger_id = "first"\n')
    assert handler.handle("prepare", {}).status == 200
    assert export_current(config, handler.settings.config.path)
    assert not export_current(config, tmp_path / "other.json")
    source.write_text('trigger_id = "second"\n')
    assert handler.payload()["exported"] is False
    assert handler.handle("prepare", {}).status == 200
    assert tomllib.loads((project / "data/webui.toml").read_text())["trigger_id"] == "second"


def test_generation_only_outputs_files_not_arbitrary_commands(handler):
    handler.handle("mail", account(password=SECRET, username="user; echo unsafe@example.org"))
    assert handler.handle("prepare", {}).status == 200
    path = handler.settings.config.load().workspace_path / ".nanobot/mail/himalaya.toml"
    data = tomllib.loads(path.read_text())["accounts"]["work"]["imap"]["sasl"]["plain"]
    assert data["username"] == "user; echo unsafe@example.org"
    assert all("echo unsafe" not in arg for arg in data["password"]["command"])
