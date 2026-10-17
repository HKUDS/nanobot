# Inspecting an update

This branch connects the WebUI update entry to exact-release preparation and a
detached installer/restart worker. It is not itself a published release. Published
stable installations keep their existing updater until this code ships, and preview
publication remains a separate release-pipeline step.

Existing users first receive this feature by upgrading through their original
installation method. That first upgrade does not convert pip, pipx, uv or Docker
into an installer-managed installation; the owner table below still applies.
Stable users do not opt into previews merely by checking for updates.

Automatic updates require an official signed release approval as well as a package
checksum, for both Stable and Preview. Missing or invalid proof, or an unavailable
trust service, refuses the update before package mutation. Keep using the current
version and retry later; report persistent failures and the version to a maintainer.
Do not disable verification or install a replacement file from an error message.

This proof identifies the publication workflow that approved the bytes; it does
not certify that all application and dependency code is free of malicious behavior.
First installs and owner-managed pip/pipx/source/container updates retain their own
distribution trust boundaries. Automatic recovery addresses upgrade faults, not
malware execution or reversal of data theft. See the [release approval contract](releasing.md#release-approval-proof).

In **Settings → About**, **Receive preview updates** is visible below the update
check; there is no section to expand first. It is off by default. Turn it on to
try new features early, with a higher risk of bugs. There is
one update button for both release types; installing a preview shows its risk in
the confirmation. This preference alone does not download, install or restart.
It belongs to this installation, not the browser. Changes require an authenticated
local browser or the gateway's explicit remote package-install permission; other
installation owners keep their own updater. Without that permission the preference
is read-only, with guidance beside the disabled switch.

Turn it off to receive only stable updates. If this preview is newer than the latest
stable release, keep using it until a newer stable is available. This does not
downgrade packages or restore old data. A verified newer stable release remains
available when the Preview index is unavailable; an older or incomplete release
does not become a recovery target. Installing a final release while this preference
is on keeps previews enabled for the next development cycle.

Stable is not restricted to monthly releases. Validated fixes can ship as stable
patches between feature releases, without joining Preview. The release policy aims
to offer a Preview on days with eligible changes and passing release checks, not
to publish every commit or require an update every day. You can skip intermediate
previews and install the latest compatible version offered by the checker.
Normal users receive prebuilt WebUI and native TUI packages; they do not need Bun
to compile the interface. Source installations retain their development workflow.
See the [release cadence and publication gates](releasing.md#release-cadence).
Daily publication is not enabled by this PR or by turning on the preference.

If a fresh official installation fails during environment creation or download,
fix the reported prerequisite/network error and rerun the same installer command.
Its saved base-package selection preserves that environment's owner across retries;
it does not launch setup or report success until installation is verified. Do not
switch to a second package manager as recovery.

## Update from the WebUI

The sidebar's blue update entry and **Settings → About → Update** open the same
confirmation. Opening it only inspects the installation. **Update & restart** approves
that exact target, downloads and verifies the wheel and dependencies, backs up the
affected profiles, and asks the selected idle background gateways to stop. A separate
worker installs offline, verifies the files and dependencies, and restarts those
gateways. “Update complete” requires both a successful journal and a reconnected
gateway actually running the target version. It is never inferred from a timer.
Only nanobot's affected background gateways restart, not the computer or browser.
The page waits for authenticated reconnection before reading the saved result;
**Done** reloads the page to load the installed frontend assets.
If you hide the dialog, use **Settings → About → View details** to reopen the saved
update. This entry remains available even when the package version is already current;
it does not create another update or repeat installation.

Fresh official-installer environments record their base-package selection and start
`nanobot webui` with a persistent background gateway. These installations can use the
inline route without manual extras or launcher configuration. The receipt stays with
that environment and is checked again before mutation. Existing unrecorded venvs are
not silently adopted. Explicit `nanobot webui --detach` also starts a persistent
gateway; ordinary `webui` launches outside installer-managed environments retain
their previous on-demand lifetime. `--detach --dev` is unsupported.

Compatible POSIX uv 0.11.16 **registry** tool installations started with
`nanobot gateway --background` or `nanobot webui --detach` also support the inline
route. It preserves recorded extras, constraints and additional packages. Other
owners use the workflow below; an update indicator never promises universal in-app
installation.

## Installation owners

For installations that cannot update inline, the update entry names the detected
owner (for example, **Update via pipx**). It opens instructions **inside the same
dialog**, not just an external documentation link. The guide identifies the gateway
host and environment; remote users must use that server's terminal and original
installation account. Container names/paths are explicitly distinguished from the
deployment host. It does not execute commands or grant installation permission.

The guide walks through stopping affected gateways and backing up their data,
updating through the original owner, then restarting with the same profile. Copyable
commands bind the manager root or exact Python environment; pipx environment suffixes
are retained. uv upgrades preserve their recorded constraints and may choose a
different permitted stable version from the notice. A generic `pipx upgrade` can
discard the original version constraint and pip options (including index settings).
The guide only offers it for unconstrained registry installs without recorded pip
options; other pipx installs require review of their original settings. No generic upgrade is
offered for a GitHub-only Preview, fixed source, pin/lock, unknown extras or an
unconfirmed manager layout. Instead the guide explains what to inspect and preserve.
Source and container deployments get their own steps, never a guessed branch, image,
service name or destructive volume command. Documentation remains a secondary link.

**Check running gateway** reads the authenticated gateway's current settings, not
the installed package metadata or the newest release number. A mismatch and an
unreachable gateway have explicit feedback. After a restart, reconnect to the same
gateway (and reopen the guide if needed), verify the version in **About**, and check
that your configuration and chats remain present. None of these manual steps claim
the automatic backup/recovery guarantees of the official managed updater.

| Installation | Update route | Restart and recovery owner |
| --- | --- | --- |
| Fresh official installer | WebUI **Update & restart**, for a compatible prebuilt release | Detached nanobot worker; standalone recovery below |
| Existing uv registry tool | Inline only for the verified uv/platform combination above; otherwise `uv tool upgrade nanobot-ai` | Same uv environment and its original gateway launcher |
| pipx | `pipx upgrade` for an unconstrained registry install without recorded pip options; otherwise inspect and preserve the original policy first. Retain suffixes and injected packages. | pipx and the original launcher |
| Ordinary pip venv | Stop its gateways, back up data, then run that venv's Python with `-m pip install --upgrade 'nanobot-ai[<your existing extras>]'` (omit brackets for the base package) | That exact venv; the UI does not infer optional extras |
| Source checkout | Review/pull the selected ref, update its environment and build WebUI/TUI using the contribution instructions | Checkout owner; preserve local changes |
| Docker / Compose | Pull/build the chosen image and recreate the service, retaining the existing data volumes | Container/deployment owner; never pip-install into the running container |
| OS package, service manager or Desktop | Use the distributor/deployment's update operation | Original package/service owner |

Do not switch owners as a workaround for an error. Fixed wheel URLs/paths retain
their pinned source; explicitly select and verify a new artifact using the release
handoff instructions instead of assuming a registry upgrade overrides it. Suffixed,
locked or custom-manager installations require their actual recorded options.
For every external update: stop the affected writers first, retain a data backup,
update through the original owner, restart through the original launcher, and verify
the **running** version. Package-manager success alone is not a running-gateway check.

Updating is explicit, never scheduled by checking for updates. All running gateways
sharing the installation are included in the confirmation; stopped profiles are not
started. Active work prevents the shutdown handoff. Remote clients need the existing
package-install permission, and native Desktop clients use their distributor's updater.

Refreshing restores saved progress, **not installation consent**. Prepared files can
be confirmed again after their exact review has loaded. If preparation is explicitly
rejected (for example, another tab changed the channel) and a subsequent read confirms
that no job exists, the page offers a fresh review and requires confirmation again.
A timeout or lost response does not establish rejection, and a missing journal alone
does not authorize a second update. A lost execution response is resolved by reading the same job,
not creating or executing a second update. A recorded pre-mutation handoff failure
can be explicitly retried using its existing confirmation. The official managed
installation also has the independent recovery owner described below. Closing the
browser does not stop it. An offline page cannot prove the worker's status; do not
start another installation while it reconnects. Automatic data rollback is never
attempted.

## Automatic service recovery

For an installer-owned, dedicated venv with reviewed background gateways, confirming
the update also authorizes bounded recovery of that same operation. Before replacing
packages, the frozen worker preserves the complete original program and dependencies
in a verified sibling directory. Configuration, conversations and other user stores
remain in their original locations; the program copy is separate from their backup.
Insufficient snapshot space aborts installation rather than removing the old program.

An independent supervisor survives the requesting gateway and observes the worker:

1. If the worker fails or exits unexpectedly, try the already admitted exact target
   once, using the verified local files. Do not download another version, repeat the
   shutdown request or create another update.
2. If that fails before the new gateway is activated, compare protected user files
   against the original backup. Only when their contents are unchanged may recovery
   restore the original program and dependencies and restart the reviewed gateways.
   A backup failure before package mutation can restart the intact original program.
3. Verify each gateway's actual run identity, version and readiness before clearing
   maintenance. The page reports **Previous version restored**, not update success,
   and does not ask for terminal repair while automatic recovery is running.

The program switch uses journaled same-filesystem renames and keeps the failed
generation for diagnosis. One transient filesystem failure during restoration is
replayed using that journal. Duplicate launches do not get another recovery budget.
A successful upgrade removes its redundant original program copy, but retains the
original data backup. A restored service needs a fresh review and confirmation before
another update.

Recovery never restores an old conversation/configuration backup over current data.
If the candidate wrote user data or already activated, automatically running older
code could corrupt it: only same-target completion is allowed. Changed ownership,
missing/corrupt snapshots, persistent filesystem failures, unavailable base Python,
or losing both supervisor and worker (for example a power loss) can still require
operator assistance. Reservations and recovery evidence are retained instead of
guessing. This is not an OS boot-time recovery service or a zero-failure guarantee.
External package managers, unsupported installation layouts and jobs prepared by an
older version keep their documented owner/standalone recovery route; they are not
silently converted into managed installs.

## Standalone recovery

Before shutdown, preparation saves a stdlib-only launcher at
`~/.nanobot/updates/recover.py`, outside the environment being updated. The WebUI
retains the exact job ID. For installations without automatic recovery, or a
confirmed recovery failure, it can display the host's repair command. This is an
advanced fallback, not the normal managed-install failure flow. The command uses
absolute paths for both the host's base Python and
the saved launcher, so it does not depend on a working application venv, a `python`
command on PATH, or the terminal sharing the gateway's HOME. The launcher keeps its
original job/lock directory when starting the saved worker. Copy it from the WebUI
and run it **on the gateway computer, as the original OS user**. Generic examples
below assume the gateway uses that terminal's normal home directory:

```sh
python3 -I -S ~/.nanobot/updates/recover.py <job-id>
python3 -I -S ~/.nanobot/updates/recover.py <job-id> --repair
```

Windows PowerShell:

```powershell
python -I -S "$env:USERPROFILE\.nanobot\updates\recover.py" <job-id>
python -I -S "$env:USERPROFILE\.nanobot\updates\recover.py" <job-id> --repair
```

Use the Python 3.11+ command used by your installer (`py` is another common Windows
launcher). Inspection is read-only. `--repair` displays the exact saved version,
environment and backup location and asks for confirmation. `--yes` is available for
an operator who has already reviewed those facts. It launches the **original frozen
worker with the original base Python**, not the broken application's CLI.

Repair can renew expired launch consent only for an already admitted exact job. It
verifies the immutable request, original backup and staged bytes, refuses live owners
or unrelated environment changes, and reuses the same target without network access.
An installed job with a restart failure retries restart, not package installation.
This is local recovery of previously verified bytes, not a new release-eligibility
check. A prepared-only job is not installation authority. If shutdown failed before
admission, no packages changed: restart the intact gateway with its original launcher
and review a new update, or use the bounded handoff retry below while its plan is valid.

Keep the original job directory and backup until verified recovery. Missing/changed
backup, a removed base Python, disk damage or an independently modified environment
requires operator repair; the tool refuses to guess or overwrite it. Do not install
another version over a pending job, delete its fence, or restore a backup into live
data. Apart from the verified, pre-activation program-only restoration above,
downgrades and data restoration remain explicit owner-managed operations.

## Review an exact release

```bash
nanobot update --plan
nanobot update --plan --channel preview
```

Planning checks the running installation and fresh interpreter metadata, selects
a compatible prebuilt wheel, and saves an exact plan outside the package directory.
The report names the installation owner, installed and running versions, target
version, download size and hash, and whether this would be an upgrade, downgrade,
restart or no-op. It does not install anything, stop a task or restart a gateway.
It can write a private plan and release-metadata cache; it is not a zero-write command.

Plans expire after fifteen minutes. Revalidation rejects a changed interpreter
environment, version or ownership receipt, an expired plan, a withdrawn candidate,
or changed artifact bytes. It checks the version already in the plan rather than
selecting a new latest version. These checks are prerequisites for execution, not
evidence that execution or recovery has completed.

Stable metadata comes from PyPI. The complete five-platform wheel set and sdist must
be present and not yanked; unsupported platforms do not silently build from source.
Preview metadata uses the protected `release-index` catalogue of `HKUDS/nanobot`.
Until that catalogue and its approved releases are published, preview planning fails
with a network/not-available result. It does not install a Git checkout as a fallback.

The persisted catalogue rejects older generations and changed data under the same
generation. A cached catalogue cannot turn an unsuccessful network check into a fresh
result. Downloads only follow approved HTTPS hosts, use the existing DNS-pinning
transport, and check size, checksum and embedded wheel identity before staging.
An existing staged artifact is verified, never silently overwritten.

`--plan` is separate from the draft's older `--check`, release update and `--dev`
paths. Those execution paths do not consume these plans yet. Do not describe them
as implementing exact-plan consent, durable jobs, coordinated runtime maintenance,
backup or post-restart verification until the execution handoff is integrated and
tested. A plan also does not authorize bypassing uv/pipx, Docker, Desktop or an
external supervisor; the installation owner remains responsible for its files.

### Gateway review Interface

The optional `webui.update-plans.v1` capability exposes review only. On an authenticated
WebSocket, `settings.nanobot.update.plan` accepts `channel` (the saved preference
by default, or Stable if none was saved),
`restart_running` (false by default), and optional explicit `extras`. It cannot accept
a download URL, shell command, environment path or caller-supplied plan. A plain HTTP
request cannot create a plan. Review alone never authorizes installation.

The response names the gateway, exact target, running/installed versions, owner and
reviewed profiles. `restart_running=true` selects only known, running background
instances with explicit lifetime and cooperative stop support; an unknown process
owner requires its external workflow. Selection describes the impact to review. It
does not authorize shutdown, and stopped profiles are never selected for restart.
Manager-owned extras are preserved, not replaced by the client's request.

An authenticated `GET /api/settings/nanobot-update/plan?id=<plan-id>` restores the same
review after refresh. The saved record is immutable and installation-scoped. Reads
do not resolve a new target or contact the release feed. `validity` reports the local
snapshot and expiry (`current`, `expired`, `installation_changed`, `profiles_changed`),
not current release eligibility or permission to execute. All update responses are
`no-store`; missing or invalid records and discovery failures are explicit errors.

`installation_allowed` preserves the existing local/remote package-install policy.
`execution_available` reports eligibility for this exact plan; it is not authorization
and does not start work. `execution_blocked_reason` explains an incompatible owner,
policy, runtime selection or stale review. The optional `webui.update-flow.v1` client
consumes the plan through preparation and execution routes, which recheck authority
and release eligibility. It never translates it into “install latest”. Desktop
installations continue to use their distributor's updater rather than these routes.

### Saved job status

The separate optional `webui.update-jobs.read.v1` capability provides authenticated
`GET /api/settings/nanobot-update/job?id=<plan-id>`. It reads the current installation's
durable preparation/execution journal and remains `no-store`. Missing jobs return 404;
invalid identifiers return 400; corrupt or misbound records return 409. It cannot start,
cancel, repair or clean up a job and does not expose local logs or credentials.
The recovery command includes the base interpreter path needed on the gateway host;
it is display-only and is not executed by the browser.

`recorded_phase`, `attempt`, `mutation_started` and `updated_at` describe the last saved
facts, not whether a worker is alive now. The response also binds the previous/target
versions and channel to the saved plan. Plan expiry does not erase history. Reading
this record does not start the installation's Python, check a release endpoint or take
a runtime lease, so an incomplete-install marker or an active writer does not prevent
status inspection from a control plane that is still available. A dead gateway still
needs its external recovery route; this endpoint does not make that gateway reachable.
Records are scoped by environment path, so a later reinstall at that location may
still have history. A status read does not validate the new environment's fingerprint
or authorize resuming a job from its predecessor.

The consumer must not infer retry/cancel permission from a phase or treat `ready` as
proof that preparation committed. The immutable worker request remains the preparation
commit record, and execution still validates its complete inputs and current authority.

### Package-manager settings

For uv and pipx installations, planning reads the owner's existing receipt and
records a credential-free summary: selected extras, the main package's version
constraint, pin/lock status, source kind and names of additional packages. Extras
are taken from that record rather than guessed from installed dependencies. The
receipt hash binds the full original settings; planning does not rewrite it.

`owner_restriction` explains when a target conflicts with a recorded constraint,
pin, lock or unrecognized source. A null value does **not** establish that this
installation supports automatic execution. Other resolver settings still belong
to the manager, and the internal pip worker continues to reject managed environments.

The parser has receipt coverage from uv 0.11.16 and pipx 1.7.1/1.17.13 (pipx schemas
0.5 and 0.12). It rejects unrecognized schemas without exposing receipt contents
or migrating them. Reading an old receipt does not imply that an old manager
supports newer install/upgrade flags. Execution compatibility is a separate gate.

## Runtime coordination in this draft

The `nanobot` CLI entrypoint now holds a shared installation lease while running. Profiles using
the same real Python environment and OS account share it, including when launched
with different `--home` values or through a symlink. The updater requires an exclusive
lease and refuses to change package files while these runtimes are still using them.
Startup refuses while that lease is held or an interrupted-install marker remains.
An OS lock, not a PID file, owns the lease; a process crash releases it without
deleting or replacing the lock file.

This alone is not a complete maintenance handoff. In particular, the
older in-process WebUI updater cannot replace its own live gateway: it now reports
that the installation is in use instead of performing that unsafe operation. The
detached owner described below is used by the exact-plan WebUI flow. Updates refuse
unaccounted-for work and do not kill active tasks.

Leases protect cooperating entrypoints in the same account. They do not discover
older runtimes without this mechanism, arbitrary Python imports, another OS user's
processes or unrecognized supervisors. Such installations must not be advertised
as eligible for unattended/coordinated updates merely because a lease is available.

### Interactive channel connections

Settings registers channel-owned setup work with the same runtime admission gate.
A QR/browser response does not make a pending connection idle. Built-in Feishu,
WeChat, WhatsApp and Linear connectors expose their pending work and close it during
shutdown; settings retains ownership through cleanup and after a failed close.
Extensions without this lifecycle contract keep their existing connection behavior,
but cannot claim to be idle for coordinated updates while loaded.

WhatsApp's native worker must actually return before its temporary database is
promoted or removed. A shutdown timeout leaves the worker and files owned; retry
cleanup instead of interpreting a cancelled Python wrapper as a stopped native
thread. Linear releases its listener only after request threads, including webhook
writes, finish. Abandoned WhatsApp and Linear setup sessions initiate cleanup at
expiry without requiring another browser poll. Expiry or a cleanup timeout alone
does not establish that a remaining writer stopped.

### Model provider sign-in

The settings registry owns OpenAI Codex, GitHub Copilot and xAI sign-in workers
before starting them. Cancelling, expiring or replacing a sign-in removes its public
flow, but keeps it busy until its workers actually exit. A failed sign-in start
also retains ownership of any late worker. Shutdown signals cancellation and waits
for workers, callback requests and expiry timers to finish; cancelling the shutdown
awaiter does not release their ownership. Native network timeouts may delay exit.

Codex uses the SDK's public token-storage interface to reject saves after cancellation
or expiry, without moving existing credentials. This is not a new authorization
method and does not require existing users to sign in again.

These guards complement settings-request activity and actual gateway process exit.
They do not establish that every external integration writer is accounted for,
and do not enable the internal updater in the UI.

### Known gateway profiles

Gateway startup now records an installation-scoped profile receipt outside the package
being replaced. It identifies the exact interpreter/package version, selected home,
actual data directory, config and workspace paths, instance state/log paths, launch mode
and process identity. Config contents,
credentials and arbitrary environment variables are not copied into that record.
Receipts remain after exit so stopped profiles are included when planning future backups.

`--plan` includes these known profiles. A PID by itself is not liveness evidence: the
existing native process identity and runtime claim must match. A profile reused by another
installation is unconfirmed, not idle. A new or restarted profile invalidates the plan.
The executor may accept the reviewed gateways having stopped, but not a replacement
instance or an unconfirmed owner. Recording a foreground launch does not identify its
external supervisor or authorize terminating it.

This is an inventory of cooperating gateways, not discovery of all processes or a backup.
It does not authorize copying whole user workspaces. Older installations, other accounts,
external supervisors and standalone imports still require their own ownership checks.

## Exact offline executor

`update_jobs.prepare_job` now prepares an immutable plain-venv transaction. It requires
explicitly confirmed extras (including an explicit empty list for the base package),
refuses unsupported installation owners, and compares fresh interpreter and installed
metadata with the approved plan. It asks pip for a dry-run report, fetches the exact
required dependency wheels with hashes, and stages those alongside the verified
nanobot wheel. There is no source build or global package-manager fallback. Pip's
configured package sources remain its trust policy during preparation; sensitive
resolver URLs stay in a private temporary directory and are not put in the journal.

Staging alone does not authorize execution. Starting a job revalidates the same release,
checks the current environment and writes a short-lived approval bound to the exact
request. The immutable worker zipapp uses only Python's standard library and lives
outside the files being replaced. Its coordinator runs with the base interpreter;
its dedicated pip CLI child holds the installation lease itself. Killing the coordinator
therefore cannot unlock a still-running installer. Installation is offline, from only
the staged wheels, with pip's destination/configuration overrides disabled.

On POSIX, the dedicated installer replaces itself with pip's CLI through `exec`,
retaining the same PID and all installation/data lease descriptors. A failed exec
restores their non-inheritable flags; an unrelated later child cannot keep the locks.
On Windows, pip's CLI remains in the lease-owning Python process: inherited handles
are not a transfer of Windows byte-range lock ownership. Native uv/pipx execution
still requires its own verified preparation, lifecycle and recovery path; this
handoff alone does not enable it.

Windows journal readers share deletion and publishers use atomic POSIX-style
replacement, so UI polling cannot block the worker's next journal commit on
modern NTFS/ReFS. Filesystems without that operation retain ordinary atomic
rename behavior; sharing or permission failures remain visible errors. Publishing
never deletes the current record first or copies partial contents over it.

Preparation now saves the exact plan and a `preparing` journal before downloading or
resolving dependencies. Native inspection/resolution keeps its preparation leases until
it actually returns, including after repeated request cancellations. A settled failure
records `preparation_failed` without installation authority, and a retry must use the
same immutable plan. Reusing its ID for changed consent is rejected; a new review gets
a new ID.

Preparation commands now enter through the frozen worker with Python site startup
disabled. Each actual pip/probe process acquires its own runtime and native-preparation
leases before loading the mutable environment. Python probes and pip run in that
same single-use process on POSIX and Windows; the leases also cover site startup
and Python exit cleanup. Native uv retains its leases through POSIX exec; it remains
POSIX-only. The per-installation native lease also blocks another preparation and
gateway shutdown while an orphan native command is still working.

An abruptly exited preparer can leave a `preparing` record. That record alone is not
liveness evidence. The internal `settle_interrupted_preparation` operation requires
both parent and native preparation leases, then revokes the preparation generation
and records `preparation_failed`. It neither deletes staging nor starts an install.
A late child from that generation cannot execute after recovery or a new retry.
Interrupted recovery can finish recording the revoked state. The exact immutable
plan may then be prepared again if still valid; a changed plan needs a new ID.
Records predating child-owned leases cannot prove this recovery contract.

Real macOS process tests cover parent loss during a Python probe, pip and native uv,
including refusal of conflicting work, late-child rejection and subsequent retry.
They do not prove native Windows behavior or containment of arbitrary descendants
created by custom environment hooks. The authenticated public recovery action and native
platform acceptance remain separate from local application acceptance.

The journal records the attempt, phase, whether mutation began, and a bounded message.
After pip exits, a fresh interpreter must import the target from the correct environment;
application files, including bundled WebUI/TUI assets, must match the approved wheel,
and `pip check` must pass. Without selected restart participants the result is
**installed**, not “gateway updated”. With explicitly selected background participants,
the worker starts the installed runtime under protected maintenance, verifies its
identity and readiness, then activates it. Only verified activation is **succeeded**;
a failed restart retains the recovery state and does not report success.

A stopped job can be cancelled only before mutation. Failed/interrupted mutation keeps
its startup fence and exact inputs. Explicit repair rechecks eligibility and cannot
overwrite a different version installed by another updater. Within a valid approval,
the copied worker can retry or show `--status <job-directory>` without importing a
broken nanobot installation. Normal execution refuses expired approval. The standalone
recovery launcher above provides fresh, explicit local consent for the same admitted
job when the application control plane is unavailable.

### Detached shutdown and installation

`update_jobs.start_handoff` confirms an exact prepared job and starts a detached owner
using the base Python. The initiating request can return; the gateway does not await
its own exit. Shutdown consent is separate from permission to replace package files.

The owner starts a short-lived child in the old installation. That child takes a shared
installation lease **before** importing application code, rechecks the exact release
and installation, closes the release client, then requests cooperative shutdown only
from the plan's selected idle gateways. All selected gateways must prepare before any
stop is committed. It waits for actual process exit, not just an inactive receipt.
The parent waits for this preflight child to exit too, obtains exclusive installation
and data leases, and only then grants installation approval and runs the offline worker.

The saved phases distinguish checking, stopping and a failed handoff from package
mutation. A shutdown commitment is not undone by a later failure: review the saved
state before retrying. A surviving preflight child retains its lease even if its parent
crashes; it cannot install by itself, and another handoff cannot overwrite its progress.
Retrying an unmodified handoff requires fresh consent within the exact plan's lifetime.
After package mutation starts, use the explicit repair path, not shutdown again.

These internal paths are verified with real detached/pip processes and disposable
application wheels, including dependency upgrades, caller exit, coordinator loss and
repair. Preflight/restart routing fixtures do not constitute a complete application
upgrade E2E. Actual isolated gateway stop and protected restart have separate tests.
The WebUI now connects client consent, uv execution and reconnection. This does not
establish pipx execution, native Windows support or public-release acceptance. The
saved-job CLI still does not perform initial staging and execution.

### Explicit recovery before package mutation

In the WebUI, **Check again** only reads the saved update state. It never grants
fresh installation or restart consent. After a failed handoff, **Review update**
first asks the gateway to settle the old job, then shows a fresh version and restart
review. Installation starts only after a separate **Update & restart** confirmation.
This also allows an expired plan to be replaced without extending its old consent.

The optional `webui.update-jobs.settle-handoff.v1` capability extends the existing
authenticated `settings.nanobot.update.settle` action to prepared or failed handoffs.
Settlement requires the worker, preflight and stop-coordinator leases to be free;
it refuses committed shutdown, admitted installation and any package mutation.
It marks the old job cancelled without deleting its saved files or starting work.
Repeated settlement is safe; a lost response can be recovered by reading that job.
If settlement is refused, the UI keeps the original job for status checks and recovery.
Older hosts without this capability keep read-only status checks; use their existing
update or recovery instructions instead of sending an unsupported settlement action.

The optional `webui.update-jobs.retry-handoff.v1` capability accepts authenticated
WebSocket action `settings.nanobot.update.retry` with `id`,
`previous_confirmation_id` and `confirm_restart: true`. The existing package-install
policy and runtime admission checks apply. Plain HTTP cannot start a retry. This
action does not create a new plan or broaden the inline eligibility reported by the
review response.

Retry replaces exactly the saved execution confirmation the user reviewed. Repeating
that request, replaying the original execute request or using an older confirmation
only returns history. It cannot trigger another attempt. An unchanged response is
not evidence of a running worker: consumers must present the returned journal.
If the current worker or an orphan preflight child still owns its lease, retry fails
without changing consent. After both exit, recovery can cover a failed handoff or a
crash before launch/claim. A delayed process with the replaced confirmation cannot
start. The original exact plan, artifacts, expiry, release eligibility and selected
runtime identities still apply; retry cannot extend the review or repair mutation.

If the gateway has stopped **but package mutation has not begun**, the same intact
installation also provides a local entrypoint:

```bash
nanobot update --job <plan-id>
nanobot update --job <plan-id> --retry-handoff \
  --previous-confirmation <execution-confirmation-id> --confirm-restart
```

Read the first command's saved facts and the original plan before consenting to the
second. It repeats the reviewed shutdown/install/restart operation, not just a
connection check. The console owns a shared runtime lease before importing the
application; its detached owner waits for all runtime readers to exit before
installing. A successful command returns a durable job record, **not** proof that
the update or restart succeeded. It neither restarts previously stopped profiles
outside the plan nor selects a new latest release.

These commands require an intact application environment. They refuse an incomplete
installation marker and are **not** the recovery solution for broken dependencies
or post-mutation repair. Use the independent `recover.py` entrypoint above instead.
