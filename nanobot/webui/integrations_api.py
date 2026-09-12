"""Authenticated integrations settings domain: write-only credentials, no execution."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from nanobot.config.integrations import ICloudIntegrationConfig, MailAccountConfig
from nanobot.config.schema import Config
from nanobot.integrations.credentials import CredentialStore, PrivateStoreError
from nanobot.integrations.export import export_current, prepare_configs
from nanobot.integrations.status import evolution_status, memory_status, service_status
from nanobot.webui.settings_contracts import SettingsRouteResult
from nanobot.webui.settings_services import WebUISettingsServices


class IntegrationsSettingsHandler:
    def __init__(self, settings: WebUISettingsServices):
        self.settings = settings

    def payload(self) -> dict[str, Any]:
        config = self.settings.config.load()
        integrations = config.personal_integrations
        credentials = CredentialStore(config.workspace_path)
        icloud = integrations.icloud.model_dump(exclude={"credential_ref"})
        icloud["credential_configured"] = credentials.configured(integrations.icloud.credential_ref)
        accounts: list[dict[str, Any]] = []
        for account in integrations.mail_accounts:
            item = account.model_dump(exclude={"credential_ref"})
            item["credential_configured"] = credentials.configured(account.credential_ref)
            accounts.append(item)
        return {
            "icloud": icloud,
            "mail": {"accounts": accounts, "dry_run": True,
                     "reconcile_interval_seconds": integrations.reconcile_interval_seconds},
            "memory": memory_status(config), "evolution": evolution_status(config),
            "services": service_status(config.workspace_path),
            "exported": export_current(config, self.settings.config.path),
            "notes": [
                "Zapis konfiguracji nie uruchamia usług ani nie sprawdza połączenia z kontem.",
                "Hasła aplikacji są przechowywane oddzielnie, lokalnie, z prawami 0600/0700; nie jest to szyfrowany sejf.",
                "Poczta: tylko IMAPS/TLS i hasło aplikacji. OAuth/SMTP nie są konfigurowane przez ten panel.",
                "Wygenerowana poczta zawsze pozostaje w dry-run. Brak wysyłania, usuwania i automatycznej aktywacji.",
                "Tryb pamięci/Evolution oznacza zapisane ustawienie; liczba rekordów nie jest dowodem aktywności procesu.",
            ],
        }

    def handle(self, action: str, payload: dict[str, Any] | None) -> SettingsRouteResult:
        try:
            if action == "status":
                return SettingsRouteResult.success(self.payload())
            if payload is None:
                return SettingsRouteResult.failure(400, "Wymagany obiekt danych WebSocket.")
            if action == "prepare":
                if payload:
                    return SettingsRouteResult.failure(400, "Przygotowanie nie przyjmuje parametrów.")
                self.settings.config.run_serialized(
                    lambda path: prepare_configs(self.settings.config.load(), path))
                message = "Przygotowano konfiguracje usług. Niczego nie uruchomiono; najpierw sprawdź połączenie i dry-run."
            elif action in {"icloud", "mail"}:
                self._save(action, payload)
                message = "Zapisano ustawienia. Hasło nie jest zwracane. Przygotuj konfiguracje usług przed ich uruchomieniem."
            else:
                return SettingsRouteResult.failure(404, "Nieznana operacja integracji.")
            result = self.payload()
            result["message"] = message
            return SettingsRouteResult.success(result)
        except ValidationError:
            # Even unknown field names may contain secrets; don't echo them.
            return SettingsRouteResult.failure(400, "Niepoprawna konfiguracja. Sprawdź login, host, port, godziny oraz reguły i dozwolone foldery.")
        except PrivateStoreError as exc:
            return SettingsRouteResult.failure(400, str(exc))
        except Exception:
            # Never include raw configuration, paths, secrets or backend diagnostics.
            return SettingsRouteResult.failure(500, "Nie udało się obsłużyć konfiguracji integracji. Sprawdź uprawnienia i dostępność komponentów.")

    def _save(self, action: str, payload: dict[str, Any]) -> None:
        values = dict(payload)
        password = values.pop("password", None)
        if password is not None and (not isinstance(password, str) or len(password) > 4096
                                     or any(c in password for c in "\r\n\x00")):
            raise PrivateStoreError("Niepoprawny format hasła aplikacji.")
        if "credential_ref" in values or "credentialRef" in values:
            raise PrivateStoreError("Referencją sekretu zarządza serwer.")
        # Validate before creating a secret or changing config.
        parsed = ICloudIntegrationConfig.model_validate(values) if action == "icloud" else MailAccountConfig.model_validate(values)
        new_reference = ""
        store: CredentialStore | None = None

        def mutate(config: Config) -> None:
            nonlocal new_reference, store
            settings = config.personal_integrations
            store = CredentialStore(config.workspace_path)
            if isinstance(parsed, ICloudIntegrationConfig):
                previous = settings.icloud
            else:
                previous = next((a for a in settings.mail_accounts if a.id == parsed.id), None)
                if previous is None and len(settings.mail_accounts) >= 20:
                    raise PrivateStoreError("Maksymalnie 20 kont IMAP.")
            if password:
                new_reference = store.put(password)
                parsed.credential_ref = new_reference
            elif previous is not None:
                # Do not send an existing account's credential to a changed server or identity.
                changed_identity = previous.username != parsed.username
                if isinstance(parsed, MailAccountConfig) and isinstance(previous, MailAccountConfig):
                    changed_identity |= (previous.host, previous.port) != (parsed.host, parsed.port)
                if changed_identity and previous.credential_ref:
                    raise PrivateStoreError("Zmiana serwera lub loginu wymaga ponownego podania hasła aplikacji.")
                parsed.credential_ref = previous.credential_ref
            if isinstance(parsed, ICloudIntegrationConfig):
                settings.icloud = parsed
            else:
                if previous is None:
                    settings.mail_accounts = [*settings.mail_accounts, parsed]
                else:
                    settings.mail_accounts = [parsed if a.id == parsed.id else a for a in settings.mail_accounts]
        try:
            self.settings.config.update(mutate)
        except Exception:
            if new_reference and store is not None:
                store.discard_uncommitted(new_reference)
            raise
