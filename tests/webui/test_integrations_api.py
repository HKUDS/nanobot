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
from webui.test_settings_routes import _mutation_request, _router

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
    result = handler.handle("icloud", {"username": "another@example.org", "password": ""})
    assert result.status == 200
    assert icloud_credentials(handler.settings.config.path)[:2] == ("another@example.org", SECRET)
    assert handler.settings.config.load().personal_integrations.icloud.sleep_hours == 9


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


@pytest.mark.parametrize("name", ["motis", "firefly_iii"])
def test_connection_slots_inert_private_and_bound_to_endpoint(handler, name):
    initial = handler.payload()["connection_slots"][name]
    assert initial["enabled"] is False
    assert initial["read_only"] is True
    assert initial["status"] == "adapter_not_installed"
    result = handler.handle(name, {"base_url": "https://service.example.org/", "password": SECRET})
    assert result.status == 200
    assert SECRET not in repr(result)
    assert SECRET not in handler.settings.config.path.read_text()
    saved = getattr(handler.settings.config.load().personal_integrations, name)
    assert saved.base_url == "https://service.example.org"
    assert result.payload["connection_slots"][name]["credential_configured"] is True
    assert "credential_ref" not in result.payload["connection_slots"][name]
    assert handler.handle(name, {"base_url": saved.base_url}).status == 200
    assert getattr(handler.settings.config.load().personal_integrations, name).credential_ref == saved.credential_ref
    assert handler.handle(name, {"base_url": "https://other.example.org"}).status == 400


@pytest.mark.parametrize("values", [
    {"enabled": True}, {"read_only": False}, {"credential_ref": "a" * 32},
    {"base_url": "https://user:password@example.org"}, {"base_url": "https://example.org?token=secret"},
    {"base_url": "file:///etc/passwd"}, {"base_url": "http://example.org"},
    {"base_url": "http://169.254.169.254"}, {"base_url": "https://example.org:0"},
    {"base_url": "https://example.org", "password": "bad\nsecret"}, {"password": SECRET},
])
def test_connection_slot_rejects_activation_unsafe_url_and_secrets(handler, values):
    before = handler.settings.config.path.read_bytes()
    result = handler.handle("firefly_iii", values)
    assert result.status == 400
    assert SECRET not in repr(result)
    assert handler.settings.config.path.read_bytes() == before


def test_connection_slot_secret_cleanup_after_failed_write(handler, monkeypatch):
    monkeypatch.setattr("nanobot.webui.settings_services.save_config",
                        lambda *args: (_ for _ in ()).throw(OSError(SECRET)))
    result = handler.handle("firefly_iii", {"base_url": "https://example.org", "password": SECRET})
    assert result.status == 500
    assert SECRET not in repr(result)
    directory = handler.settings.config.load().workspace_path / ".nanobot/integrations/secrets"
    assert not list(directory.iterdir())


@pytest.mark.parametrize("path", ["/api/settings/integrations/motis", "/api/settings/integrations/firefly-iii"])
def test_connection_slots_are_ws_only_mutations(path):
    from nanobot.webui.settings_routes import WebUISettingsRouter
    assert WebUISettingsRouter.is_mutation_path(path)


@pytest.mark.parametrize('key', ['personalIntegrations', 'personal_integrations'])
def test_root_integration_config_aliases_roundtrip(key):
    from nanobot.config.schema import Config
    config = Config.model_validate({key: {'motis': {'baseUrl': 'https://motis.example.org'}}})
    assert config.personal_integrations.motis.base_url == 'https://motis.example.org'
    assert config.model_dump(by_alias=True)['personalIntegrations']['motis']['readOnly'] is True


def test_apple_link_is_idempotent_shared_and_fixed(handler):
    first = handler.handle("icloud", {"username": "apple@example.org", "password": SECRET})
    assert first.status == 200
    saved = handler.settings.config.load().personal_integrations
    assert len(saved.mail_accounts) == 1
    mail = saved.mail_accounts[0]
    assert (mail.host, mail.port, mail.managed_by) == ("imap.mail.me.com", 993, "icloud")
    assert mail.credential_ref == saved.icloud.credential_ref
    assert mail.folder_policy == "all" and not mail.rules
    assert first.payload["icloud"]["linked_mail_account_id"] == mail.id
    assert "credential_ref" not in repr(first.payload)
    reference = mail.credential_ref
    for password in ("", None):
        values = {"username": "edited@example.org"}
        if password is not None:
            values["password"] = password
        assert handler.handle("icloud", values).status == 200
    saved = handler.settings.config.load().personal_integrations
    assert len(saved.mail_accounts) == 1
    assert saved.mail_accounts[0].id == mail.id
    assert saved.mail_accounts[0].username == "edited@example.org"
    assert saved.mail_accounts[0].credential_ref == saved.icloud.credential_ref == reference
    assert handler.handle("icloud", {"password": "new-apple-secret"}).status == 200
    saved = handler.settings.config.load().personal_integrations
    assert saved.mail_accounts[0].credential_ref == saved.icloud.credential_ref != reference
    store = CredentialStore(handler.settings.config.load().workspace_path)
    assert store.get(saved.icloud.credential_ref) == "new-apple-secret"
    assert store.get(reference) == SECRET  # previous exports/backups still reference it


def test_apple_adopts_matching_legacy_mail_without_losing_rules(handler):
    assert handler.handle("mail", account(
        id="old-apple", username="apple@example.org", email="apple@example.org",
        host="imap.mail.me.com", password="old-mail-password",
    )).status == 200
    old = handler.settings.config.load().personal_integrations.mail_accounts[0]
    assert handler.handle("icloud", {"username": "apple@example.org", "password": SECRET}).status == 200
    settings = handler.settings.config.load().personal_integrations
    assert len(settings.mail_accounts) == 1
    saved = settings.mail_accounts[0]
    assert saved.id == "old-apple" and saved.managed_by == "icloud"
    assert saved.rules == old.rules and saved.allowed_folders == old.allowed_folders
    assert saved.folder_policy == "allowlist"
    assert saved.credential_ref == settings.icloud.credential_ref != old.credential_ref
    assert handler.handle("icloud", {"username": "changed@example.org"}).status == 200
    saved = handler.settings.config.load().personal_integrations.mail_accounts[0]
    assert saved.id == "old-apple" and saved.rules == old.rules


def test_linked_mail_identity_and_credential_owned_by_apple(handler):
    assert handler.handle("icloud", {"username": "apple@example.org", "password": SECRET}).status == 200
    linked = handler.settings.config.load().personal_integrations.mail_accounts[0]
    for changes in ({"host": "other.example.org"}, {"password": "new-password"},
                    {"email": "other@example.org"}, {"username": "other@example.org"},
                    {"managed_by": None}):
        before = handler.settings.config.path.read_bytes()
        assert handler.handle("mail", {"id": linked.id, **changes}).status == 400
        assert handler.settings.config.path.read_bytes() == before
    assert handler.handle("mail", {"id": linked.id, "folder_policy": "all",
                                   "rules": [{"name": "review", "destination": "Review",
                                              "sender_globs": ["*@example.org"]}]}).status == 200
    assert handler.handle("icloud", {"username": "new@example.org"}).status == 200
    assert len(handler.settings.config.load().personal_integrations.mail_accounts[0].rules) == 1


def test_apple_id_collision_does_not_replace_generic_account(handler):
    assert handler.handle("mail", account(id="icloud", password=SECRET)).status == 200
    old = handler.settings.config.load().personal_integrations.mail_accounts[0]
    assert handler.handle("icloud", {"username": "apple@example.org", "password": "apple-password"}).status == 200
    accounts = handler.settings.config.load().personal_integrations.mail_accounts
    assert len(accounts) == 2 and accounts[0] == old
    assert accounts[1].id == "icloud-2" and accounts[1].managed_by == "icloud"


def test_default_all_folders_without_rules_exports_without_time_manager(handler):
    assert handler.handle("icloud", {"username": "apple@example.org", "password": SECRET}).status == 200
    assert handler.handle("prepare", {}).status == 200
    root = handler.settings.config.load().workspace_path / ".nanobot/mail"
    worker = tomllib.loads((root / "config.toml").read_text())
    account_config = worker["accounts"]["icloud"]
    assert account_config["folder_policy"] == "all"
    assert not account_config["allowed_folders"] and not account_config.get("rules")
    assert worker["worker"]["dry_run"] is True
    plain = tomllib.loads((root / "himalaya.toml").read_text())["accounts"]["icloud"]["imap"]["sasl"]["plain"]
    assert plain["password"]["command"][-1] == handler.settings.config.load().personal_integrations.icloud.credential_ref


def test_partial_mail_edit_keeps_existing_rules_and_restrictions(handler):
    assert handler.handle("mail", account(password=SECRET)).status == 200
    old = handler.settings.config.load().personal_integrations.mail_accounts[0]
    assert handler.handle("mail", {"id": "work", "email": "new@example.org", "password": ""}).status == 200
    saved = handler.settings.config.load().personal_integrations.mail_accounts[0]
    assert saved.rules == old.rules and saved.folder_policy == "allowlist"
    assert saved.credential_ref == old.credential_ref
    # Explicit all-folder mode preserves optional proposals, not move permission.
    assert handler.handle("mail", {"id": "work", "folder_policy": "all"}).status == 200
    assert handler.settings.config.load().personal_integrations.mail_accounts[0].rules == old.rules


@pytest.mark.parametrize("payload", [{}, {"target": "arbitrary"}, {"target": "mail"},
                                      {"target": "icloud", "host": "other.example.org"},
                                      {"target": "icloud", "password": SECRET},
                                      {"target": "icloud", "account_id": "work"}])
def test_connection_check_contract_rejects_overrides(handler, monkeypatch, payload):
    monkeypatch.setattr("nanobot.webui.integrations_api.check_connection", lambda *args: pytest.fail("invalid probe"))
    result = handler.handle("check", payload)
    assert result.status == 400 and SECRET not in repr(result)


def test_connection_check_does_not_save_or_export(handler, monkeypatch):
    calls = []
    def check(config, request):
        calls.append(request.model_dump())
        return {"ok": True, "read_only": True, "checks": []}
    monkeypatch.setattr("nanobot.webui.integrations_api.check_connection", check)
    before = handler.settings.config.path.read_bytes()
    assert handler.handle("check", {"target": "icloud"}).payload["ok"] is True
    assert calls == [{"target": "icloud", "account_id": None}]
    assert handler.settings.config.path.read_bytes() == before


def test_apple_link_capacity_failure_rolls_back_new_secret(handler):
    for index in range(20):
        assert handler.handle("mail", account(id=f"mail-{index}", password=SECRET)).status == 200
    before = handler.settings.config.path.read_bytes()
    directory = handler.settings.config.load().workspace_path / ".nanobot/integrations/secrets"
    references = set(directory.iterdir())
    assert handler.handle("icloud", {"username": "apple@example.org", "password": "new-secret"}).status == 400
    assert handler.settings.config.path.read_bytes() == before
    assert set(directory.iterdir()) == references


def test_manual_mail_cannot_duplicate_the_linked_apple_account(handler):
    assert handler.handle("icloud", {"username": "apple@example.org", "password": SECRET}).status == 200
    duplicate = account(id="duplicate", email="apple@example.org", username="apple@example.org",
                        host="imap.mail.me.com", password="new-password")
    assert handler.handle("mail", duplicate).status == 400
    assert len(handler.settings.config.load().personal_integrations.mail_accounts) == 1


def test_partial_save_preserves_camelcase_api_support(handler):
    assert handler.handle("icloud", {"username": "apple@example.org", "password": SECRET}).status == 200
    assert handler.handle("icloud", {"sleepHours": 9}).status == 200
    assert handler.settings.config.load().personal_integrations.icloud.sleep_hours == 9
    assert handler.handle("mail", account(password=SECRET)).status == 200
    assert handler.handle("mail", {"id": "work", "folderPolicy": "all"}).status == 200
    assert handler.settings.config.load().personal_integrations.mail_accounts[1].folder_policy == "all"
