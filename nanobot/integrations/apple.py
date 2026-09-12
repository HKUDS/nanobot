"""Link Apple Calendar and iCloud IMAP to one server-owned credential source."""
from __future__ import annotations

from nanobot.config.integrations import (
    ICloudIntegrationConfig,
    MailAccountConfig,
    PersonalIntegrationsConfig,
)
from nanobot.integrations.credentials import PrivateStoreError


def link_icloud_mail(
    settings: PersonalIntegrationsConfig, icloud: ICloudIntegrationConfig,
) -> PersonalIntegrationsConfig:
    """Idempotently adopt a matching legacy IMAP account or create one linked account.

    Existing folder restrictions/rules and the stable account ID survive Apple
    edits. A generic credential is never adopted: Apple is always the source.
    """
    if not icloud.username or "@" not in icloud.username:
        raise PrivateStoreError("Podaj adres e-mail konta Apple.")
    accounts = settings.mail_accounts
    linked = next((account for account in accounts if account.managed_by == "icloud"), None)
    if linked is None:
        identities = {icloud.username.casefold(), settings.icloud.username.casefold()}
        linked = next((account for account in accounts
                       if (account.host, account.port) == ("imap.mail.me.com", 993)
                       and account.username.casefold() in identities), None)
    values: dict[str, object]
    if linked is None:
        if len(accounts) >= 20:
            raise PrivateStoreError("Maksymalnie 20 kont IMAP; brak miejsca na połączone konto Apple.")
        used_ids = {account.id for account in accounts}
        account_id = "icloud"
        index = 2
        while account_id in used_ids:
            account_id = f"icloud-{index}"
            index += 1
        values = {"id": account_id}
    else:
        values = linked.model_dump()
    values.update(email=icloud.username, username=icloud.username,
                  host="imap.mail.me.com", port=993, managed_by="icloud",
                  credential_ref=icloud.credential_ref)
    account = MailAccountConfig.model_validate(values)
    updated = [account if existing.id == account.id else existing for existing in accounts]
    if linked is None:
        updated.append(account)
    return PersonalIntegrationsConfig.model_validate({
        **settings.model_dump(), "icloud": icloud, "mail_accounts": updated,
    })
