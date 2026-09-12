# iCloud calendar monitor

Read-only CalDAV monitor for Nanobot. It discovers all calendars, polls every five
minutes, stores progress in SQLite and queues calendar changes through a local
trigger. Calendar titles and descriptions are untrusted input.

## Installation

Install the gateway from this repository, then install the service in the same
Python environment:

```bash
python -m pip install -e . -e services/icloud-calendar
```

Runtime data stays outside the checkout. The Integrations panel prepares
`~/.nanobot/workspace/projects/icloud-time-manager/data/webui.toml`. That file
references the gateway credential store; it never contains the Apple password.
An Apple app-specific password is shared with the linked iCloud mailbox.
The existing environment-variable credential mode is also supported.

Use the generated configuration to verify the local route and read access:

```bash
python -m time_manager.preflight --config /path/to/data/webui.toml
nanobot-calendar --config /path/to/data/webui.toml check
nanobot-calendar --config /path/to/data/webui.toml scan --dry-run
nanobot-calendar --config /path/to/data/webui.toml run
nanobot-calendar --config /path/to/data/webui.toml status
```

`preflight` checks the configured recipient, trigger and credentials locally.
`check` and `scan --dry-run` verify Apple access without changing calendar events
or sending notifications. `status` reads the last scan health file. Trigger
queue acceptance is distinct from confirmed Telegram delivery.

## Service management

Adapt the paths and service user in `deploy/nanobot-time-manager.service` to the
installation. Keep the state directory writable and credentials private. The
unit includes preflight, automatic restart, a restrictive umask and filesystem
hardening. It can run alongside the gateway and mail worker.

The defaults are `calendar_only=true` and `auto_manage_sleep=false`, including
when those keys are omitted from a configuration. Sleep, wake-up and briefing
planning remains deferred. The legacy planning code is covered by explicit
opt-in tests; saving Apple credentials never activates it.

## Verification

```bash
python -m pip install -e 'services/icloud-calendar[dev]'
cd services/icloud-calendar
ruff check .
python -m pytest -q
python -m pip wheel --no-deps --wheel-dir dist .
```

Tests isolate the network and do not send messages or modify Apple data. GitHub
Actions runs these checks when the service or gateway integration changes.
Configuration, credentials, SQLite state and health files are excluded from Git.
