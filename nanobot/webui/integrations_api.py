"""Authenticated integrations settings domain: write-only credentials, no execution."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from nanobot.config.integration_slots import IntegrationSlot
from nanobot.config.integrations import ICloudIntegrationConfig, MailAccountConfig
from nanobot.config.schema import Config
from nanobot.integrations.apple import link_icloud_mail
from nanobot.integrations.credentials import CredentialStore, PrivateStoreError
from nanobot.integrations.diagnostics import CheckRequest, check_connection
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
        icloud["linked_mail_account_id"] = next(
            (account.id for account in integrations.mail_accounts if account.managed_by == "icloud"), None)
        accounts: list[dict[str, Any]] = []
        for account in integrations.mail_accounts:
            item = account.model_dump(exclude={"credential_ref"})
            item["credential_configured"] = credentials.configured(account.credential_ref)
            accounts.append(item)
        return {
            "icloud": icloud,
            "connection_slots": {
                name: {**slot.model_dump(exclude={"credential_ref"}),
                       "credential_configured": credentials.configured(slot.credential_ref),
                       "status": "adapter_not_installed"}
                for name, slot in (("motis", integrations.motis), ("firefly_iii", integrations.firefly_iii))
            },
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
            if action == "check":
                request = CheckRequest.model_validate(payload)
                return SettingsRouteResult.success(check_connection(self.settings.config.load(), request))
            if action == "prepare":
                if payload:
                    return SettingsRouteResult.failure(400, "Przygotowanie nie przyjmuje parametrów.")
                self.settings.config.run_serialized(
                    lambda path: prepare_configs(self.settings.config.load(), path))
                message = "Przygotowano konfiguracje usług. Niczego nie uruchomiono; najpierw sprawdź połączenie i dry-run."
            elif action in {"motis", "firefly_iii"}:
                self._save_slot(action, payload)
                message = "Zapisano miejsce integracji. Adapter nie jest aktywny; nie wykonano żadnego połączenia ani operacji."
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
            return SettingsRouteResult.failure(400, "Niepoprawna konfiguracja. Sprawdź adres e-mail, login, host i port.")
        except PrivateStoreError as exc:
            return SettingsRouteResult.failure(400, str(exc))
        except Exception:
            # Never include raw configuration, paths, secrets or backend diagnostics.
            return SettingsRouteResult.failure(500, "Nie udało się obsłużyć konfiguracji integracji. Sprawdź uprawnienia i dostępność komponentów.")

    def _save_slot(self, action: str, payload: dict[str, Any]) -> None:
        values = dict(payload)
        token = values.pop("password", None)
        if token is not None and (not isinstance(token, str) or len(token) > 8192
                                  or any(ord(c) < 32 for c in token)):
            raise PrivateStoreError("Niepoprawny format tokenu.")
        if "credential_ref" in values or "credentialRef" in values:
            raise PrivateStoreError("Referencją sekretu zarządza serwer.")
        parsed = IntegrationSlot.model_validate(values)
        new_reference = ""
        store: CredentialStore | None = None

        def mutate(config: Config) -> None:
            nonlocal store, new_reference
            previous = getattr(config.personal_integrations, action)
            store = CredentialStore(config.workspace_path)
            if token:
                if not parsed.base_url:
                    raise PrivateStoreError("Najpierw podaj adres usługi.")
                new_reference = store.put(token)
                parsed.credential_ref = new_reference
            else:
                if previous.credential_ref and previous.base_url != parsed.base_url:
                    raise PrivateStoreError("Zmiana adresu usługi wymaga ponownego podania tokenu.")
                parsed.credential_ref = previous.credential_ref
            setattr(config.personal_integrations, action, parsed)

        try:
            self.settings.config.update(mutate)
        except Exception:
            if new_reference and store is not None:
                store.discard_uncommitted(new_reference)
            raise

    def _save(self, action: str, payload: dict[str, Any]) -> None:
        values = dict(payload)
        password = values.pop("password", None)
        if password is not None and (not isinstance(password, str) or len(password) > 4096
                                     or any(c in password for c in "\r\n\x00")):
            raise PrivateStoreError("Niepoprawny format hasła aplikacji.")
        if "credential_ref" in values or "credentialRef" in values:
            raise PrivateStoreError("Referencją sekretu zarządza serwer.")
        if "managed_by" in values or "managedBy" in values:
            raise PrivateStoreError("Połączeniem konta Apple zarządza serwer.")
        fields = ICloudIntegrationConfig.model_fields if action == "icloud" else MailAccountConfig.model_fields
        # Merge partial edits in one spelling; retain Base's camelCase compatibility
        # without alias+field duplicates from a previous snake_case model_dump.
        for name, field in fields.items():
            if field.alias and field.alias != name and field.alias in values:
                if name in values:
                    raise PrivateStoreError("Nie podawaj tego samego pola dwukrotnie.")
                values[name] = values.pop(field.alias)
        new_reference = ""
        store: CredentialStore | None = None

        def mutate(config: Config) -> None:
            nonlocal new_reference, store
            settings = config.personal_integrations
            store = CredentialStore(config.workspace_path)
            if action == "icloud":
                # The simple Apple form must not reset hidden legacy preferences.
                parsed = ICloudIntegrationConfig.model_validate({**settings.icloud.model_dump(), **values})
                if not parsed.username or "@" not in parsed.username:
                    raise PrivateStoreError("Podaj adres e-mail konta Apple.")
                if password:
                    new_reference = store.put(password)
                    parsed.credential_ref = new_reference
                # Explicitly authorized Apple username edits preserve the credential:
                # both consumers have fixed Apple endpoints, never a new mail host.
                config.personal_integrations = link_icloud_mail(settings, parsed)
                return

            previous = next((a for a in settings.mail_accounts if a.id == values.get("id")), None)
            parsed = MailAccountConfig.model_validate({
                **(previous.model_dump() if previous else {}), **values,
            })
            if previous is None and len(settings.mail_accounts) >= 20:
                raise PrivateStoreError("Maksymalnie 20 kont IMAP.")
            if any(
                a.id != parsed.id and a.managed_by == "icloud" and (a.host, a.port, a.username.casefold()) ==
                (parsed.host, parsed.port, parsed.username.casefold()) for a in settings.mail_accounts
            ):
                raise PrivateStoreError("Połączone konto iCloud już istnieje; użyj panelu Apple.")
            if previous is not None:
                changed_identity = (previous.username, previous.host, previous.port) != (
                    parsed.username, parsed.host, parsed.port)
                if previous.managed_by == "icloud" and (
                    changed_identity or previous.email != parsed.email or password
                ):
                    raise PrivateStoreError("Login i hasło połączonego konta zmień w panelu Apple.")
                if changed_identity and previous.credential_ref and not password:
                    raise PrivateStoreError("Zmiana serwera lub loginu wymaga ponownego podania hasła aplikacji.")
            if password:
                new_reference = store.put(password)
                parsed.credential_ref = new_reference
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
