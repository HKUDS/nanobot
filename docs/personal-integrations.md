# Personal integrations in WebUI

Open **Settings → Integracje** to configure Apple and personal IMAP accounts, and inspect semantic memory, Evolution, and fixed service statuses. This is separate from the Email chat-channel autoresponder. Apple is a conventional credential-backed integration; saving it does not activate sleep/wake automation.

## What the panel does

- Reads current configuration and available status data on demand.
- Adds/updates up to 20 IMAP accounts, with a public hostname, implicit TLS (IMAPS), and app password. **All selectable folders are available by default; rules are optional.** Existing explicit restrictions and ordered sender/subject rules are preserved when omitted from an edit.
- The Apple form accepts an email/login and app-specific password. It idempotently creates or adopts one linked iCloud IMAP account at **`imap.mail.me.com:993` with verified TLS**, sharing the same server-owned credential reference as Apple CalDAV. Repeated saves, login edits, and password rotation update that account, not a duplicate. A matching legacy account keeps its ID, restrictions, and rules. Hidden legacy time-manager preferences are not reset by the simpler form.
- Prepares consumer TOML files on explicit request. Saving or preparing does **not** start/restart services or connect to accounts. The separate **connection check** performs only authenticated IMAP LIST / CalDAV PROPFIND reads; local validation alone is not a connection test.
- Leaves all generated mail configuration in `dry_run = true`. All-folder policy additionally forbids MOVE even if a hand-edited worker sets `dry_run=false`. No send, delete, calendar mutation, SMTP or OAuth broker is introduced. Existing manually reviewed, explicitly allowlisted worker deployments are unchanged.

All mutations use the existing authenticated WebSocket settings transport. HTTP GET cannot mutate settings. The panel has no endpoint for reading a password, running a command, selecting arbitrary paths, or changing safety/Evolution policy.

## Credentials and privacy

Public configuration is declared by `PersonalIntegrationsConfig` in the root config's `personalIntegrations` field. Passwords are stored separately beneath the gateway workspace:

```
.nanobot/integrations/secrets/<opaque-reference>
```

Files are `0600`, directories `0700` on POSIX. This is a **local file store, not encryption or an OS keychain**. Protect the host disk, backups, and administrator account. Use HTTPS/WSS or a local SSH tunnel when entering credentials. Do not send real passwords in chat.

The UI accepts passwords as write-only inputs, clears them after submission and never stores them in browser storage. Blank/omitted means preserve the existing credential. **Apple login edits also preserve it**, as explicitly authorized: both consumer endpoints remain fixed Apple services. **Generic IMAP host, port or login changes still require a fresh password**; an old credential is never reused against a changed mail host. A linked account's login/password is edited only through Apple; mail policy/rules may be edited separately. API clients cannot set `managed_by` or `credential_ref`. Failed config writes remove newly created, uncommitted credentials. Previous referenced credentials are retained for manually managed consumers/backups and are never returned by API responses.

TOML contains only a fixed, shell-free consumer command (`python -m nanobot.integrations.credentials`) pointing to an opaque reference. The helper emits a secret only to its consumer's stdout pipe. Never run it interactively or put its output in logs. No arbitrary secret commands are accepted from WebUI.

## Preparing service configuration

The **Przygotuj konfiguracje usług** button writes:

- `.nanobot/mail/config.toml` — mail worker, `dry_run=true`, optional rules, and explicit `folder_policy`; `all` discovers sources dynamically rather than limiting polling to INBOX;
- `.nanobot/mail/himalaya.toml` — named IMAPS accounts and credential commands;
- `.nanobot/mail/carillon.toml` — fixed account hooks using `enqueue-env`, not shell interpolation;
- `projects/icloud-time-manager/data/webui.toml` — when the existing time-manager project is installed and iCloud credentials are saved. It references this gateway's config and preserves the existing trigger ID from `data/config.toml`; the original file remains untouched.

The time-manager consumer is optional: its absence no longer blocks an Apple mail export, and nothing installs or activates it. If already installed, the monitor reads saved credentials through `nanobot_config_path` in `webui.toml`; without that field it retains its existing environment-variable behavior. To inspect that existing consumer's configuration, select it explicitly:

```bash
python -m time_manager.cli --config data/webui.toml check
python -m time_manager.cli --config data/webui.toml scan --dry-run
```

Run these in the installed time-manager directory using the Nanobot interpreter. Review the result and delivery channel before starting `run`. A missing trigger means no proactive delivery; the panel does not create a new trigger or cron. Existing manually managed mail configs are never overwritten. An export manifest checks exact hashes and the source config/trigger identity; manual edits cause a safe refusal. Exports sharing a workspace use `.nanobot/integrations/export.lock`, and recheck target contents immediately before replacement. Coordinate external editors with that same lock (or stop editing during export); a non-cooperating external filesystem writer cannot be given a strict no-race guarantee. Interrupted multi-file exports can be retried, and are not reported current until every file matches.

## Folder discovery and reconciliation

New accounts default to `folder_policy = "all"`. The worker runs bounded `himalaya --json imap list --all` on **every reconciliation pass**, not merely at export time. This uses IMAP LIST, including unsubscribed/nested folders, rather than subscription-only LSUB. It skips `\\Noselect` / `\\NonExistent` entries, normalizes only the case-insensitive INBOX name, and checks UIDVALIDITY before and after each UID search. Newly created folders are discovered on the next 120–300 second pass. Carillon retains its INBOX push hook; reconciliation covers every other selectable folder and repairs missed events. Discovery failure is reported, not silently treated as successful INBOX-only coverage; one failed account/folder does not block others.

Responses, folder counts (default 1,000), message counts and command duration are bounded. Folder names are validated and passed as argv, never shell input. Raw reads omit Himalaya's `--seen` flag. With no rules or explicit legacy fallback destination, messages are recorded as `no_action` without downloading their content; existing rules remain dry-run proposals. `folder_policy="allowlist"` preserves explicitly configured legacy sources and destination restrictions. Legacy nonempty allowlists are inferred as restrictive when no policy was saved; switching to `all` must be explicit and does not erase their rules.

## Read-only diagnostics API

Use the existing authenticated WebSocket settings action `settings.integrations.check` (route `/api/settings/integrations/check`):

```json
{"target": "icloud"}
```

or `{"target":"mail","account_id":"work"}`. It accepts **no** URL, host, password, command or timeout override. Invalid requests return 400. Operational failure returns a normal report with `ok:false`, not a raw exception:

```json
{"target":"mail","account_id":"work","read_only":true,"timeout_seconds":12,
 "ok":true,"checks":[{"service":"imap","ok":true,"code":"ok","message":"…","folder_count":5}]}
```

Apple checks IMAPS login/LIST and a depth-zero CalDAV current-user-principal PROPFIND. No messages are selected/fetched and no event is created. The report is ephemeral, contains no folder names, principal IDs, secrets or provider error text, and is not persisted. Public-only DNS validation rejects mixed private/public answers; the validated IP is pinned to the socket while TLS certificate verification and SNI use the saved hostname. Redirects are refused without forwarding credentials. One global probe slot, a 12-second request deadline, socket deadlines, and response bounds prevent unbounded work; a stuck system resolver holds that single slot and subsequent checks return `busy` until it exits. A successful check proves access at that moment, **not** worker deployment or ongoing synchronization.

Status adds `icloud.linked_mail_account_id` and `mail.accounts[].managed_by` (`"icloud"` or `null`) plus `folder_policy`. These are not credential references. Do not round-trip server-owned metadata into save requests. Existing accounts without a link are linked on the next explicit Apple save, not on GET.

## Interpreting status

- Gateway “responding” means the process serving this request is alive.
- A service is active/inactive only if a recognized systemd unit reports it. Unknown does not mean stopped; a manually launched process may not have such a unit.
- Memory counts come from a bounded read-only query scoped to the configured workspace namespace. Missing dependencies/DB return `null`, not a fabricated zero. No migration, reindex or purge runs during a status read.
- Evolution counts read existing observations, without creating the engine or storage. Configuration mode is not proof of process liveness. Missing/oversized/unreadable logs are reported explicitly.
- “Prepared” means hashes match saved configuration, not that credentials worked or services started.

## Verification and deployment

Backend tests: `pytest tests/webui/test_integrations_api.py tests/webui/test_integration_diagnostics.py`; watcher tests: `PYTHONPATH=services/mail-watcher/src pytest services/mail-watcher/tests`. Broader route tests cover the shared authentication boundary. Frontend tests cover forms, secret clearing, failed requests and multiple accounts. Run TypeScript/build and inspect desktop/mobile rendering before deploying.

The gateway must be restarted to load new Python route code. Deploy the matching built WebUI assets, then reload the page; old route code plus new UI alone is not a completed rollout. Restart through the existing service manager/UI control, not a second gateway process. No credentials or automation activation are required to test the panel itself.

## MOTIS and Firefly III connection slots

Settings → Integracje includes separate MOTIS and Firefly III forms for a base URL and an optional write-only token. Both are **inert slots**: no runtime adapter, HTTP request, routing computation or financial action runs when saving them. `enabled` must remain false and `readOnly` true until a separately reviewed adapter is installed. Secrets use the private store described above; API responses expose presence only. Switching endpoints requires a fresh token when one was previously saved. Both camelCase `personalIntegrations` and legacy `personal_integrations` root keys are supported.
