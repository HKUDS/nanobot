"""Prepare versioned consumer configuration, without starting any service."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tomllib
from pathlib import Path

from filelock import FileLock
from pydantic import BaseModel, Field, ValidationError

from nanobot.config.schema import Config
from nanobot.integrations.credentials import (
    CredentialStore,
    PrivateStoreError,
    atomic_private_write,
    private_path,
)

MARKER = "# Managed by Nanobot Integrations WebUI v1\n"


class ExportManifest(BaseModel):
    fingerprint: str = ""
    files: dict[str, str] = Field(default_factory=dict)
    previous_files: dict[str, str] = Field(default_factory=dict)


def quote(value: str) -> str:
    # JSON basic strings are compatible with TOML for validated values.
    return json.dumps(value, ensure_ascii=False)


def array(values: list[str]) -> str:
    return "[" + ", ".join(quote(v) for v in values) + "]"


def _monitor_trigger(config: Config) -> str:
    source = private_path(config.workspace_path, "projects/icloud-time-manager/data/config.toml")
    if not source.is_file():
        return ""
    if source.stat().st_size > 64_000:
        raise PrivateStoreError("Konfiguracja monitora przekracza limit odczytu.")
    value = tomllib.loads(source.read_text(encoding="utf-8")).get("trigger_id", "")
    if not isinstance(value, str):
        raise PrivateStoreError("Niepoprawny identyfikator triggera monitora.")
    return value


def fingerprint(config: Config, config_path: Path, *, trigger_id: str | None = None) -> str:
    data = {
        "settings": config.personal_integrations.model_dump(),
        "config_path": str(config_path.resolve()), "workspace": str(config.workspace_path.resolve()),
        "python": sys.executable, "himalaya": _binary("himalaya"), "nanobot_mail": _binary("nanobot-mail"),
        "trigger_id": (trigger_id if trigger_id is not None else _monitor_trigger(config))
        if config.personal_integrations.icloud.username else "",
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return str(Path(found).resolve())
    candidate = Path.home() / ".local" / "bin" / name
    return str(candidate)  # Missing CLI is reported separately; never install here.


def prepare_configs(config: Config, config_path: Path) -> dict[str, str]:
    lock_path = private_path(config.workspace_path, ".nanobot/integrations/export.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # All panel instances sharing this workspace serialize exports. External
    # editors should use the same lock or edit only while services are stopped.
    with FileLock(str(lock_path), timeout=5):
        return _prepare_locked(config, config_path)


def _prepare_locked(config: Config, config_path: Path) -> dict[str, str]:
    settings = config.personal_integrations
    workspace = config.workspace_path.resolve()
    secrets = CredentialStore(workspace)
    files: dict[str, str] = {}
    if settings.mail_accounts:
        worker = [MARKER, "[worker]", 'database = "state/events.sqlite3"',
                  f"himalaya_binary = {quote(_binary('himalaya'))}", 'himalaya_config = "himalaya.toml"',
                  "dry_run = true", f"reconcile_interval_seconds = {settings.reconcile_interval_seconds}"]
        himalaya = [MARKER]
        carillon = [MARKER]
        for index, account in enumerate(settings.mail_accounts):
            if not secrets.configured(account.credential_ref):
                raise PrivateStoreError("Najpierw zapisz hasło aplikacji dla każdego konta poczty.")
            credential_cmd = [sys.executable, "-m", "nanobot.integrations.credentials", "--workspace",
                              str(workspace), "--ref", account.credential_ref]
            backend = [f"[accounts.{account.id}]", f"default = {'true' if index == 0 else 'false'}",
                       f"imap.server = {quote(f'imaps://{account.host}:{account.port}')}",
                       f"imap.sasl.plain.username = {quote(account.username)}",
                       f"imap.sasl.plain.password.command = {array(credential_cmd)}"]
            himalaya.extend([*backend, f"email = {quote(account.email)}", ""])
            hook = [_binary("nanobot-mail"), "--config", str(workspace / ".nanobot/mail/config.toml"),
                    "enqueue-env", "--account", account.id]
            carillon.extend([*backend, 'imap.mailbox = "INBOX"',
                             f"imap.hook.on-message-added.cmd = {array(hook)}", ""])
            worker.extend(["", f"[accounts.{account.id}]", 'source_mailboxes = ["INBOX"]',
                           f"allowed_folders = {array(account.allowed_folders)}"])
            for rule in account.rules:
                worker.extend(["", f"[[accounts.{account.id}.rules]]", f"name = {quote(rule.name)}",
                               f"destination = {quote(rule.destination)}",
                               f"sender_globs = {array(rule.sender_globs)}",
                               f"subject_contains = {array(rule.subject_contains)}"])
        files.update({".nanobot/mail/config.toml": "\n".join(worker) + "\n",
                      ".nanobot/mail/himalaya.toml": "\n".join(himalaya) + "\n",
                      ".nanobot/mail/carillon.toml": "\n".join(carillon) + "\n"})
    icloud = settings.icloud
    trigger_id = _monitor_trigger(config) if icloud.username else ""
    if icloud.username:
        if not secrets.configured(icloud.credential_ref):
            raise PrivateStoreError("Najpierw zapisz hasło aplikacji iCloud.")
        project = private_path(workspace, "projects/icloud-time-manager")
        if not (project / "time_manager/cli.py").is_file():
            raise PrivateStoreError("Brak zainstalowanego monitora czasu; konfiguracja iCloud jest zapisana.")
        data = icloud.model_dump(exclude={"username", "credential_ref"})
        data.update(nanobot_config_path=str(config_path), workspace_path=str(workspace),
                    state_path="data/state.sqlite3", trigger_id=trigger_id)
        lines = [MARKER]
        for key, value in data.items():
            rendered = quote(value) if isinstance(value, str) else str(value).lower()
            lines.append(f"{key} = {rendered}")
        files["projects/icloud-time-manager/data/webui.toml"] = "\n".join(lines) + "\n"
    if not files:
        raise PrivateStoreError("Zapisz najpierw konfigurację iCloud lub konta IMAP.")

    # Preflight all targets before touching any. Never overwrite manually managed config.
    paths = {name: private_path(workspace, name) for name in files}
    manifest_path = private_path(workspace, ".nanobot/integrations/export.json")
    manifest = read_export_manifest(config)
    hashes = manifest.files
    previous_hashes = manifest.previous_files
    snapshots: dict[str, bytes | None] = {}
    for name, path in paths.items():
        tomllib.loads(files[name])
        snapshots[name] = None
        if path.exists():
            if path.stat().st_size > 1_000_000:
                raise PrivateStoreError("Konfiguracja usług przekracza limit odczytu.")
            snapshot = path.read_bytes()
            snapshots[name] = snapshot
            allowed = {hashes.get(name), previous_hashes.get(name)}
            if hashlib.sha256(snapshot).hexdigest() not in allowed:
                raise PrivateStoreError("Istniejąca konfiguracja usług nie jest zarządzana przez panel lub została zmieniona ręcznie. Nie nadpisano jej.")
    manifest_payload = {"fingerprint": fingerprint(config, config_path, trigger_id=trigger_id), "files": {
        name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()},
        "previous_files": {name: hashlib.sha256(content).hexdigest()
                           for name, content in snapshots.items() if content is not None}}
    # Write intent first: a crash can leave a partial export, but GET will report
    # exported=false and repeating prepare accepts only our old/new exact hashes.
    atomic_private_write(manifest_path, json.dumps(manifest_payload).encode())
    for name, path in paths.items():
        # Detect edits since preflight, and revalidate symlink boundaries before
        # replacement. Non-cooperating filesystem editors still need coordination.
        path = private_path(workspace, name)
        if path.exists() and path.stat().st_size > 1_000_000:
            raise PrivateStoreError("Konfiguracja zmieniła się w trakcie eksportu. Przerwano zapis.")
        current = path.read_bytes() if path.exists() else None
        if current != snapshots[name]:
            raise PrivateStoreError("Konfiguracja zmieniła się w trakcie eksportu. Przerwano zapis.")
        atomic_private_write(path, files[name].encode())
    manifest_payload.pop("previous_files")
    atomic_private_write(manifest_path, json.dumps(manifest_payload).encode())
    return files


def read_export_manifest(config: Config) -> ExportManifest:
    path = private_path(config.workspace_path, ".nanobot/integrations/export.json")
    if not path.exists() or path.stat().st_size > 64_000:
        return ExportManifest()
    try:
        return ExportManifest.model_validate_json(path.read_text())
    except (OSError, ValidationError):
        return ExportManifest()


def export_current(config: Config, config_path: Path) -> bool:
    manifest = read_export_manifest(config)
    if manifest.fingerprint != fingerprint(config, config_path):
        return False
    if not manifest.files:
        return False
    for name, digest in manifest.files.items():
        path = private_path(config.workspace_path, name)
        if not path.is_file() or path.stat().st_size > 1_000_000:
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return False
    return True
