# Personal integrations in WebUI

Open **Settings → Integracje** to configure personal IMAP accounts and the iCloud time manager, and inspect semantic memory, Evolution, and fixed service statuses. This is separate from the Email chat-channel autoresponder.

## What the panel does

- Reads current configuration and available status data on demand.
- Adds/updates up to 20 IMAP accounts, with a public hostname, implicit TLS (IMAPS), app password, destination allowlist and ordered sender/subject rules.
- Configures iCloud username, app password, timezone, sleep duration, wake time, preparation and briefing offsets, and a dedicated managed-calendar name.
- Prepares consumer TOML files on explicit request. It does **not** start or restart services, test credentials, connect to mailboxes, or send/move/delete mail or calendar events. Local validation is not a connection test.
- Leaves all generated mail configuration in `dry_run = true`; enabling real actions remains a separate reviewed operation. OAuth brokers and SMTP are not exposed by this initial panel.

All mutations use the existing authenticated WebSocket settings transport. HTTP GET cannot mutate settings. The panel has no endpoint for reading a password, running a command, selecting arbitrary paths, or changing safety/Evolution policy.

## Credentials and privacy

Public configuration is declared by `PersonalIntegrationsConfig` in the root config's `personalIntegrations` field. Passwords are stored separately beneath the gateway workspace:

```
.nanobot/integrations/secrets/<opaque-reference>
```

Files are `0600`, directories `0700` on POSIX. This is a **local file store, not encryption or an OS keychain**. Protect the host disk, backups, and administrator account. Use HTTPS/WSS or a local SSH tunnel when entering credentials. Do not send real passwords in chat.

The UI accepts passwords as write-only inputs, clears them after submission and never stores them in browser storage. Blank/omitted means preserve the existing credential. Changing the login or mail server requires a fresh password so an old credential is not silently sent to a new identity/endpoint. Failed config writes remove newly created, uncommitted credentials. Previous referenced credentials are retained for manually managed consumers/backups and are never returned by API responses.

TOML contains only a fixed, shell-free consumer command (`python -m nanobot.integrations.credentials`) pointing to an opaque reference. The helper emits a secret only to its consumer's stdout pipe. Never run it interactively or put its output in logs. No arbitrary secret commands are accepted from WebUI.

## Preparing service configuration

The **Przygotuj konfiguracje usług** button writes:

- `.nanobot/mail/config.toml` — mail worker, `dry_run=true`, approved rules and INBOX sources;
- `.nanobot/mail/himalaya.toml` — named IMAPS accounts and credential commands;
- `.nanobot/mail/carillon.toml` — fixed account hooks using `enqueue-env`, not shell interpolation;
- `projects/icloud-time-manager/data/webui.toml` — when the existing time-manager project is installed and iCloud credentials are saved. It references this gateway's config and preserves the existing trigger ID from `data/config.toml`; the original file remains untouched.

The monitor reads saved credentials through `nanobot_config_path` in `webui.toml`; without that field it retains its existing environment-variable behavior. To use the generated configuration, select it explicitly:

```bash
python -m time_manager.cli --config data/webui.toml check
python -m time_manager.cli --config data/webui.toml scan --dry-run
```

Run these in the installed time-manager directory using the Nanobot interpreter. Review the result and delivery channel before starting `run`. A missing trigger means no proactive delivery; the panel does not create a new trigger or cron. Existing manually managed mail configs are never overwritten. An export manifest checks exact hashes and the source config/trigger identity; manual edits cause a safe refusal. Exports sharing a workspace use `.nanobot/integrations/export.lock`, and recheck target contents immediately before replacement. Coordinate external editors with that same lock (or stop editing during export); a non-cooperating external filesystem writer cannot be given a strict no-race guarantee. Interrupted multi-file exports can be retried, and are not reported current until every file matches.

## Interpreting status

- Gateway “responding” means the process serving this request is alive.
- A service is active/inactive only if a recognized systemd unit reports it. Unknown does not mean stopped; a manually launched process may not have such a unit.
- Memory counts come from a bounded read-only query scoped to the configured workspace namespace. Missing dependencies/DB return `null`, not a fabricated zero. No migration, reindex or purge runs during a status read.
- Evolution counts read existing observations, without creating the engine or storage. Configuration mode is not proof of process liveness. Missing/oversized/unreadable logs are reported explicitly.
- “Prepared” means hashes match saved configuration, not that credentials worked or services started.

## Verification and deployment

Backend tests: `pytest tests/webui/test_integrations_api.py`; broader route tests cover the shared authentication boundary. Frontend tests cover forms, secret clearing, failed requests and multiple accounts. Run TypeScript/build and inspect desktop/mobile rendering before deploying.

The gateway must be restarted to load new Python route code. Deploy the matching built WebUI assets, then reload the page; old route code plus new UI alone is not a completed rollout. Restart through the existing service manager/UI control, not a second gateway process. No credentials or automation activation are required to test the panel itself.
