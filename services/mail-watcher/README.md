# Nanobot Mail Watcher

A small, separately deployable bridge between [Carillon](https://github.com/pimalaya/carillon) and [Himalaya](https://github.com/pimalaya/himalaya). Carillon reports IMAP IDLE events, this service stores them durably, and a worker uses a deliberately narrow Himalaya adapter to classify and move mail.

This directory contains **generic source code only**. Real account configuration, credentials, message data, the SQLite queue, and audit records must live outside the repository.

## Current milestone

Implemented in v0.2:

- concurrent, durable SQLite intake from Carillon hooks;
- idempotency using `account + mailbox + UIDVALIDITY + UID`;
- recovery of work interrupted by a crash;
- bounded exponential retries and permanent failure state;
- deterministic, ordered header rules;
- all-folder discovery by default, with optional rules and legacy source/destination allowlists;
- `dry_run = true` by default; all-folder mode is always read-only regardless of that switch;
- shell-free Himalaya calls limited to `list`, `status`, `search`, `read`, and explicitly allowlisted `move`;
- append-only, data-minimized audit rows for queue and routing transitions;
- per-claim ownership tokens and lease renewal before external operations;
- UIDVALIDITY checks before reads and immediately before moves;
- ambiguous post-MOVE recovery that stops for manual review instead of repeating MOVE;
- periodic reconciliation of every approved source mailbox (default: every 3 minutes);
- UIDVALIDITY checks before and after each bounded IMAP SEARCH listing;
- private `0700` state directory and `0600` database on POSIX;
- systemd user-service templates.

Not implemented yet:

- Nanobot/LLM classification for ambiguous messages;
- alerts and draft creation;
- a post-move destination UID check.

Sending, forwarding, and deleting are intentionally absent from the adapter.

## Data boundary

Keep these files in a private runtime directory such as:

```text
~/.nanobot/workspace/.nanobot/mail/
├── config.toml       # routing policy; mode 600
├── carillon.toml     # IMAP endpoint/user; mode 600
├── himalaya.toml     # mail client config; mode 600
└── state/
    └── events.sqlite3
```

Do not commit this directory. Audit decisions omit sender and sender addresses, and Himalaya stderr is not persisted. Database records can still reveal account names, mailbox names, configured UIDs, routing folders, and operational errors, so the database remains private. Passwords and OAuth tokens should be returned by a secret-store command; they should not be embedded in TOML.

## Install for development

```bash
cd services/mail-watcher
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
```

For a local user install:

```bash
python3 -m pip install --user ./services/mail-watcher
```

The runtime itself has no Python dependencies outside the standard library. Configure `himalaya_binary` as an absolute path; the worker does not search `PATH` for this privileged executable.

## Configure

Copy `config/mail.example.toml` to the private runtime location, replace the example account and folders, and keep dry-run enabled:

```bash
install -d -m 700 ~/.nanobot/workspace/.nanobot/mail
install -m 600 config/mail.example.toml \
  ~/.nanobot/workspace/.nanobot/mail/config.toml
```

Configure the same account name in Himalaya and Carillon. Copy `config/carillon.example.toml`, replace absolute paths and credentials, then validate each component:

```bash
himalaya account check example
carillon -a example check
nanobot-mail --config ~/.nanobot/workspace/.nanobot/mail/config.toml check
nanobot-mail --config ~/.nanobot/workspace/.nanobot/mail/config.toml init
```

## Hook and worker flow

Carillon invokes only the fast enqueue command. Its argv-list hook exports event values as lowercase environment variables; list entries themselves are not templates. The example therefore uses a fixed account argument and the dedicated environment boundary:

```bash
nanobot-mail --config /PRIVATE/PATH/config.toml enqueue-env --account example
```

`enqueue-env` reads only Carillon's fixed `mailbox` and `id` environment names, then applies the same account, approved-source, mailbox, and UID validation as explicit enqueue. It does not invoke a shell or evaluate values. Carillon does not currently export UIDVALIDITY, so hook events begin with an unknown namespace. The worker obtains UIDVALIDITY through `himalaya --json imap status` before fetching the message and promotes the provisional event identity. Duplicate promoted events are completed without a second action.

Run an explicit missed-event reconciliation and one processing batch during testing:

```bash
nanobot-mail -c /PRIVATE/PATH/config.toml reconcile
nanobot-mail -c /PRIVATE/PATH/config.toml work --once
nanobot-mail -c /PRIVATE/PATH/config.toml status
nanobot-mail -c /PRIVATE/PATH/config.toml audit EVENT_ID
```

The long-running worker performs the same reconciliation immediately after startup and then every `reconcile_interval_seconds` (120–300 seconds). With `folder_policy = "all"`, each pass discovers selectable folders using `himalaya --json imap list --all` (LIST, including unsubscribed/nested folders), skips `\\Noselect`/`\\NonExistent`, and then reconciles each folder. Carillon can keep its INBOX push hook; polling covers all other folders and newly created folders. Failed discovery is reported rather than silently falling back to INBOX. `folder_policy = "allowlist"` instead scans explicit `source_mailboxes`. Legacy configs with explicit sources/nonempty allowlists retain that policy unless changed explicitly.

The worker isolates failures by account/mailbox and idempotently enqueues only UID results whose UIDVALIDITY is unchanged across the listing. `reconcile_max_folders` (default 1,000), `reconcile_max_messages`, and `reconcile_max_response_bytes` bound each listing. An oversized response fails that listing without affecting other accounts. A restart safely repeats the scan because known identities are unique in SQLite. Himalaya 2.1 IMAP LIST JSON must contain `{"mailboxes":[{"name":"INBOX","attributes":[],"delimiter":"/"}]}`; unknown/unsafe responses fail closed.

Himalaya v2.1.0 serializes IMAP SEARCH JSON as an object with `uid_mode` and an `ids` array of `{\"id\": UID}` rows. The adapter requires `uid_mode = true`, never passes `--seq`, and rejects malformed, duplicate, or excessive IDs. Shared `message read` and `message move` commands are forced through `--backend=imap`, preventing an account's JMAP configuration from changing message identity.

No rules are required: messages without a match finish as `no_action`. If neither rules nor an explicit legacy fallback destination exists, their content is not downloaded. Reads omit `--seen` so flags remain unchanged. All-folder mode always keeps rule results as dry-run proposals and never grants MOVE permission. For existing explicitly reviewed `folder_policy = "allowlist"` deployments only, `dry_run = false` retains the legacy ability to move to destinations in `allowed_folders`; the WebUI never exports that setting.

## Rule semantics

Rules are evaluated in order. Within one rule:

- separate groups (`sender_globs`, `subject_contains`, `header_contains`) are ANDed;
- values inside a group are ORed;
- matching is case-insensitive;
- message bodies are never used by deterministic rules.

Email is untrusted data. No header or body value is interpreted as a command, executable path, destination folder, or policy update.

## systemd

Templates in `deploy/` contain `@HOME@`. Replace it with the absolute home directory and install them under `~/.config/systemd/user/`. The worker needs write access only to the private mail state directory. Enable services only after both `check` commands pass:

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-mail-worker.service carillon.service
```

## Delivery semantics

Queue transitions are transactional, but IMAP MOVE and the final local SQLite commit cannot be one distributed transaction. Immediately before MOVE, the worker records `move_started`. If the command times out or the worker dies before recording success, the next attempt enters permanent manual-review failure instead of repeating MOVE. This favors avoiding an incorrect second move over automatic recovery. A later milestone will record and verify destination UIDs where the backend exposes `COPYUID`/`MOVE` mappings.
