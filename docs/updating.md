# Updating nanobot

Use the update method that owns your installation. If your version does not include the WebUI updater, first upgrade through the original installer or package manager. This does not convert an existing installation into an installer-managed one.

## Update from the WebUI

1. Open the blue update entry in the sidebar or **Settings → About → Update**. Opening the dialog only checks the installation; it does not install or restart anything.
2. Review the exact version and affected gateways. Active work must finish before shutdown. Gateways that were already stopped are not started by the update.
3. Choose **Update & restart**. nanobot downloads and verifies the required files, backs up affected profiles, installs the update, and restarts the selected background gateways—not your computer or browser.
4. Wait for **Update complete**, which requires a reconnected gateway running the target version. Choose **Done** to reload the updated interface. If you hide the dialog, reopen it through **Settings → About → View details**.

Inline updates support fresh official-installer environments and compatible POSIX uv 0.11.16 registry tool installations running a background gateway. Other installations show their own update instructions in the dialog; see [Installation owners](#installation-owners). Remote browsers need the gateway's explicit package-install permission.

On a local macOS desktop, the background WebUI's Dock icon stays available after closing the terminal and disappears when the gateway stops. A restarted or restored gateway recreates it after activation; it may disappear during package replacement and is not an update progress indicator. `--no-dock` remembers your choice for that instance. See the [Dock controls](webui.md#macos-dock-icon).

Automatic installation requires official release approval and verified package checksums for both Stable and Preview. If verification fails, keep using the current version, retry later, and report persistent errors to a maintainer. Do not disable verification or install a replacement file from an error message. Verification confirms release approval; it is not a guarantee that all application or dependency code is harmless.

## Stable and Preview

**Settings → About → Receive preview updates** is off by default. Enable it to try new features earlier, with a higher risk of bugs. The preference applies to this installation, not just the browser; changing it requires the same local or remote permission as installing packages. It never downloads, installs, or restarts on its own.

Turn it off to receive only stable updates. If your Preview is newer than the latest stable release, nanobot keeps it until a newer stable release is available; it does not downgrade or restore old data. Installing a final release while Preview is enabled keeps Preview enabled for the next development cycle. You can skip intermediate previews.

Stable fixes can arrive between feature releases. Preview availability depends on verified publication, not a promise of daily updates. Package-manager commands outside nanobot do not read this preference; choose their version or channel explicitly.

## Installation owners

When inline installation is unavailable, the update dialog identifies the installation method and guides you through its update. Run copied commands **on the gateway computer, as the original installation account**. For containers, use the deployment host rather than treating a container path as a host path.

| Installation | Update route |
| --- | --- |
| Fresh official installer | Use WebUI **Update & restart** for a compatible release. Existing unrecorded environments are not automatically adopted. |
| uv registry tool | Use the supported inline flow above, or `uv tool upgrade nanobot-ai` in its original environment. Keep recorded extras, constraints and additional packages; a pin needs an explicitly reviewed new constraint. |
| pipx | Use `pipx upgrade nanobot-ai` only for an unconstrained registry install without recorded pip options. Otherwise preserve the original requirement, index/options, suffix and injected packages through the owner's workflow. |
| Ordinary pip venv | Use that environment's Python with `-m pip install --upgrade 'nanobot-ai[<your existing extras>]'`; omit brackets for the base package. Do not guess optional extras. |
| Source checkout | Preserve local changes, update the selected ref and environment, and follow the [development instructions](../CONTRIBUTING.md). Source is not the Preview release channel. |
| Docker / Compose | Pull or build the selected image and recreate the service with its existing data volumes. Do not pip-install into a running container. |
| OS package, service manager or Desktop | Use the distributor or deployment's updater and launcher. |

For an external update, stop all affected writers, back up configuration and data, update through the original installation method, then restart the same profiles through their original launcher. New versions may migrate stored data. Verify the **running** version in **About** and check that configuration and conversations remain available. Package-manager success alone does not verify the gateway, and manual updates do not inherit the managed updater's automatic recovery.

Do not switch package managers to work around an error. Fixed wheel sources, locked requirements and custom installations need their original settings reviewed. If a fresh official installation fails, fix the reported prerequisite or network error and rerun the same installer command.

## Recover an interrupted update

Refreshing restores saved progress, **not installation consent**. A staged update may ask you to review and confirm it again. A disconnected page cannot tell whether the worker stopped: do not start another installation while it reconnects. Closing the browser does not stop the managed update or its recovery.

**Check again** only reads saved status. **Review update** asks the gateway to settle an interrupted preparation or failed handoff before opening a fresh review. Settlement is refused while an owner is active or the operation has progressed too far to discard safely. It does not prepare or install another update; that requires a separate **Update & restart** confirmation.

If settlement is refused or its response is lost, the saved job remains available for status checks and recovery. A timeout or missing response is not permission to create a second update. After package changes have begun, use recovery rather than trying another installation.

## Automatic service recovery

For installer-owned dedicated environments with supported background gateways, the update confirmation also authorizes bounded recovery of that exact operation. nanobot retains a separate copy of the original program and dependencies before changing packages; insufficient space aborts installation.

If installation fails, recovery tries the already approved target once using saved files. If that also fails before the new gateway is activated, it can restore the original program and restart the reviewed gateways **only if protected user data is unchanged**. The dialog reports **Previous version restored**, not update success. A restored service needs a fresh review before another update.

Recovery never replaces current configuration or conversations with an old backup. Changed user data, missing or corrupt saved files, changed installation ownership, persistent disk errors, a missing base Python, or loss of both recovery processes can require operator help. Keep the saved job and backup; do not delete recovery markers or install over them. This is not recovery after every power loss or a guarantee against malicious code. Other installation methods retain their original recovery route.

## Standalone recovery

When automatic recovery is unavailable or reports failure, the WebUI can show a repair command containing the saved job ID and exact Python and launcher paths. Copy that command and run it **on the gateway computer, as the original OS user**. It does not require a working nanobot environment, but it does need the original base Python.

The following examples assume the gateway uses your terminal's normal home directory and a Python 3.11+ command. Prefer the exact paths shown by the WebUI when they differ.

macOS / Linux:

```sh
python3 -I -S ~/.nanobot/updates/recover.py <job-id>
python3 -I -S ~/.nanobot/updates/recover.py <job-id> --repair
```

Windows PowerShell:

```powershell
python -I -S "$env:USERPROFILE\.nanobot\updates\recover.py" <job-id>
python -I -S "$env:USERPROFILE\.nanobot\updates\recover.py" <job-id> --repair
```

The first command only inspects the job. `--repair` shows its saved version, environment and backup, then asks for confirmation; `--yes` skips that prompt only when used with `--repair`. Repair reuses the same verified files without downloading another release. If installation finished but restart failed, it retries restart rather than reinstalling packages. Merely preparing files does not make a job eligible for repair.

Keep the original job directory and backup until recovery is verified. Missing or changed files and an independently modified environment require operator repair. Do not restore backups over live data. Downgrading and restoring user data are separate, owner-managed operations.

## Review an exact release

```bash
nanobot update --plan
nanobot update --plan --channel preview
```

These commands save a plan showing the installation method, installed and running versions, exact target, download details and expected action. They may write plan and metadata-cache files, but do not install, stop tasks or restart gateways. `--channel` is a one-time inspection; it does not change your saved subscription.

Plans expire after fifteen minutes. Execution rechecks the reviewed release and refuses changed installations, withdrawn releases or changed artifacts. A plan is not installation permission. The separate `nanobot update`, `--check` and `--dev` commands do not execute saved plans; see the [CLI reference](cli-reference.md#updating).

## Explicit recovery before package mutation

If shutdown failed **before package changes began** and the application environment is still intact, you can inspect the saved job and explicitly retry its reviewed operation:

```bash
nanobot update --job <plan-id>
nanobot update --job <plan-id> --retry-handoff \
  --previous-confirmation <execution-confirmation-id> --confirm-restart
```

Read the saved facts and original plan before running the second command: it approves shutdown, installation and restart, not just a connection check. The same plan must still be valid, and live owners prevent retry. An accepted request is not proof of completion; check the saved result and running gateway.

These commands cannot repair a broken installation or packages already changed by an interrupted update. Use [standalone recovery](#standalone-recovery) instead.

For contributor-facing APIs, ownership and execution rules, see [Update protocol](update-protocol.md). Maintainers should use the [release checklist](releasing.md).
