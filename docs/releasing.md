# Release checklist

Use this checklist with the [Release Packaging Contract](../CONTRIBUTING.md#release-packaging-contract). Preparing a release does not publish it. Pushing a Git tag, publishing a GitHub Release, uploading to PyPI, and deploying the documentation are separate operations.

## Prepare a candidate

1. Choose the previous release and the exact candidate commit. Work in a clean worktree; do not include local configuration, session data, credentials, or unrelated changes.
2. Update `project.version` in `pyproject.toml` and the final source-only fallback in `nanobot/__init__.py`. Private WebUI/TUI package versions are not the Python release version.
3. Review the changes since the previous tag. Write highlights, upgrade and rollback guidance, contributor acknowledgements, and the full changelog. Verify counts against the final range; commit counts are not merged-PR counts. Coordinate security disclosures separately.
4. Run the Python, WebUI, and TUI checks from CI. Confirm the final commit's CI status, not just an earlier PR head. Review installation, configuration, session, and API changes.
5. Build in a clean output directory with `uv build --out-dir <artifact-directory>`. Do not set `NANOBOT_SKIP_WEBUI_BUILD`. The build hook bundles the WebUI in the sdist and wheel; the wheel is built from the sdist.
6. Check the intermediate distributions with `twine check`, inspect their contents, and record SHA-256 hashes. Test installation in an isolated environment outside the source checkout, then test upgrading from the previous stable version using disposable configuration and sessions. Do not use a maintainer's live workspace for migration tests.
7. Prepare the matching documentation PR in `Re-bin/nanobot-web`, following its `MAINTAINING.md`. Review English and all nine translations, preserve Nightly and previous releases, update the latest-version redirects, and run the complete site quality gate. Pin source links to the checked candidate commit; confirm those source files match the eventual tag before deploying. Never advertise an unpublished version as publicly available.
8. Review the pinned Bun/OpenTUI licenses, corresponding-source materials, and relinking instructions now, not after pushing the tag. Verify the exact upstream revisions are retrievable and the runtime versions match the lockfile and notices. Obtain the maintainer's commitment to honor `tui/SOURCE_OFFER.md` for its entire stated period; tests cannot grant it.
9. Build all five native TUI targets using the same scripts as the publication workflow. Include ad-hoc signatures for macOS before packaging. Verify every archive's checksum, manifest, executable architecture, required notices/licenses, and embedded source contents. Run platform-specific smoke tests where supported; record cross-compiled-only targets as such and link exact-head CI evidence instead of claiming native execution everywhere. Bundle these archives into the five platform wheels using the command below. Check all final wheels with `twine check`, validate their RECORDs, tags and installed executable permissions, and test first launch with an empty cache and `NANOBOT_TUI_NO_DOWNLOAD=1`. The installed executable must come from `site-packages/nanobot/tui/bin/`, not the checkout or a cache.
10. Merge the release-preparation PR only after its current checks and reviews pass. Confirm the merged source tree matches the tested candidate; if it does not, rebuild and recheck before tagging. Reconcile the final changelog and documentation source references. The tag must point to this verified commit, not an unchecked later `main` tip.

### OpenAI API selector compatibility window

The temporary `providers.openai.apiType` / `api_type` conversion is supported for exactly two consecutive releases: the first release containing `nanobot/config/provider_api_migration.py` and the next release. Record the first release tag and the final supported tag in release notes. Config saves write the new `api` declaration; there is no legacy runtime selector.

Before publishing the third release, remove `provider_api_migration.py`, its import and `ProvidersConfig._migrate_legacy_api_type`, and the legacy settings query conversion in `nanobot/webui/settings_models.py`. Remove the migration-specific tests and update the configuration documentation and release notes to require the current format. Keep the current-format routing, settings, and persistence regressions.

### TUI preflight without a release tag

Use Bun 1.3.13 and a clean checkout. The local build and packaging scripts do not require a tag or GitHub Release. Run targets sequentially because native dependency preparation modifies the shared `node_modules` directory:

```bash
cd tui
bun install --frozen-lockfile
bun scripts/prepare-target.ts <target>
bun run build -- <target>
# For darwin-* only: ad-hoc sign dist/nanobot-tui-<target> before the next steps.
bun scripts/release-notices.ts <target>
python3 scripts/package-release.py <target>
```

Repeat for `darwin-arm64`, `darwin-x64`, `linux-arm64`, `linux-x64`, and `win32-x64`. On macOS, use `codesign --force --sign - <binary>` and verify the signature. The publication workflow uses pinned `rcodesign` on Linux. Keep the ten `.zip`/`.zip.sha256` outputs in a candidate-specific directory, alongside the Python build intermediates and provenance manifest. Do not include local configuration, instance backups, or test environments in upload selections.

### Build the PyPI platform wheels

From the exact release checkout, after `uv build` and the native archive checks:

```bash
uv run python -m scripts.build_tui_wheels \
  --wheel <intermediates>/nanobot_ai-X.Y.Z-py3-none-any.whl \
  --tui-dir <verified-tui-archives> \
  --out-dir <final-wheels>
```

The script verifies the Python version and RECORD, native checksums, architecture, notices and embedded source against the checkout, then writes five wheels with complete TUI bundles and regenerated RECORDs. It refuses to overwrite an existing candidate. `--target <target>` builds one platform for a targeted check. Minimum tags are macOS 13, manylinux glibc 2.17 and Windows x64; x64 builds use Bun's baseline (SSE4.2) runtime instead of requiring AVX2. Recheck both Bun and OpenTUI when upgrading either dependency. No musl or Windows ARM64 wheel is provided. Native execution checks must still validate the actual binaries; tags alone do not prove compatibility. Test pip selection for all five supported platforms.

The final PyPI upload set is **five platform wheels plus one source distribution**. Do not upload the intermediate `py3-none-any.whl` or native ZIPs to PyPI. Keep the source distribution produced by the same build; it remains usable for Python/classic and WebUI installations on other platforms.

Keep an artifact manifest with the source commit, version, filenames, hashes, checks performed, and any remaining release gates. Rebuild and recheck if the packaged source changes.

## Publish, with maintainer approval

1. Confirm all pre-tag gates above are complete. Create and push exactly `vX.Y.Z`; do not move or reuse a published version tag.
2. Create the matching GitHub Release. A draft may be used while assembling its attachments. Pushing the tag alone does not run `Publish Terminal UI` or upload anything to PyPI.
3. Attach the already verified five TUI archives and their `.sha256` files, after confirming the tag's packaged sources match the artifact manifest. Verify the uploaded bytes match their preflight hashes; never upload a naked executable.
4. If instead rebuilding through **Publish Terminal UI**, use `tag=vX.Y.Z` and confirm the already completed compliance review. Wait for all five targets and repeat artifact checks on those new outputs. Do not substitute their new bytes under the old artifact hashes.
5. Make the GitHub Release and all TUI attachments publicly available. Verify their public downloads for fallback/source-built installations. Supported platform-wheel installs do not need these downloads to start the TUI.
6. Upload only the checked `nanobot_ai-X.Y.Z.tar.gz` and the five final platform wheels to PyPI. Do not upload the intermediate universal wheel or stale files from a shared `dist/` directory. This repository has no automatic PyPI publication workflow.
7. Verify installation from PyPI, bundled WebUI startup, and bundled TUI startup without downloads in clean environments. Merge the prepared wiki PR only when the stable package is available: merging its `main` deploys the site automatically. Confirm all localized `/docs/latest/` routes select the new version and old version links still work.
8. Publish the release announcement and add the dated entry to [Release Archive](./release-archive.md). Complete any coordinated advisory publication and reporter notification. Record links and completion status in the release tracking issue.

## If a gate fails

Do not publish to PyPI while a required TUI artifact or verification is missing. Keep the documentation's public `latest` on the previous stable version until the new version is usable. If a published package needs a correction, prepare a new version; do not silently replace the code behind an existing release tag. Stop all old processes and follow the documented session rollback procedure before downgrading a migrated installation.

## Installer identity checks

Run `pytest tests/test_install_scripts.py` with `uv` and `pipx` available. These
checks use private homes, offline fixture wheels and actual package managers; they
do not start a gateway or install the real application. Unix uses `install.sh` and
Windows uses Windows PowerShell with `install.ps1`. CI provisions pipx separately
from the application's dependency environment.

The installer starts the verified persistent environment's Python in isolated mode,
not `pipx run`, a disposable tool execution or whichever `nanobot` is on PATH. An
existing recognized uv/pipx/installer-managed environment takes priority over a newly
available manager. Multiple recognized installations require an explicit manual
choice. An active ordinary venv remains an explicit target; an activated uv/pipx
environment must be updated through its manager instead of pip. Existing manager
constraints remain in force, so a pinned installation can stay at its pinned version.

A failed selected manager no longer falls through to another installation, including
on first install. Fix the reported error and retry, or deliberately choose the manual
installation route. These checks do not establish maintenance, backup or restart
safety for a running gateway; the managed in-app update lifecycle is a separate gate.

The installers also accept an exact, already downloaded native wheel from a verified
release handoff. With this version of the scripts, use `install.sh --wheel <path>
--sha256 <published-hash>` or `install.ps1 -Wheel <path> -Sha256 <published-hash>`.
Both verify the file's checksum and package/version identity before installation;
`--dry-run` / `-DryRun` performs those checks without installing or starting setup.
The existing owner is still selected first. uv retains its receipt constraints; pipx
uses its upgrade-in-place operation and carries forward the requested extras. A wheel
missing a recorded pipx extra is refused before the manager is run. Manager version
requirements are the same as the tested exact-target handoff below.

After an exact install, the persistent environment must contain the requested version
before onboarding can start. A successful pinned/locked skip is reported as a failure
to install that target, not as a successful update. Keep the downloaded wheel at its
original path because the manager can record it as the installation source. Use trusted
release metadata for the hash; a checksum alone does not authenticate an unknown publisher.

For automatic platform selection of one published version, use `install.sh --release
<version> --manifest-sha256 <trusted-manifest-hash>` or `install.ps1 -Release <version>
-ManifestSha256 <trusted-manifest-hash>`. These options read the official release's
complete manifest, select the native wheel for the target installation's Python, and
verify size, SHA-256 and wheel identity before invoking the original owner. Downloads
use the official GitHub HTTPS hosts and the user's configured HTTPS proxy. Verified
wheels remain under `~/.nanobot/downloads/releases` (override with
`NANOBOT_RELEASE_CACHE`); failed partial downloads are removed. Do not remove a cache
file while a manager still records it as its installation source.

The five supported platform tags are a closed bootstrap set; no extra Python package
or frontend toolchain is installed to choose a wheel. The package manager still checks
the target's Python and dependency requirements. In release mode, `--dry-run` / `-DryRun`
fetches and validates only the manifest: no wheel, cache, environment or setup is created.
It does not claim that wheel bytes or dependency resolution have been checked.

This is an exact-version handoff, not latest-Preview discovery or a channel subscription.
Use scripts that actually contain these options; older installers do not. It does not
stop gateways or back up data. Stop affected
writers and complete a backup first. Plain pip environments still require explicit review
of extras, and suffixed/custom installations require their own manager instructions.

## Non-publishing preview preflight

**Verify Release Candidate** is a manually dispatched preparation workflow, not an
available Preview channel. It has read-only repository permission and never creates
tags/releases, uploads to PyPI, or advances a release catalogue. It builds and structurally
checks all five platform wheels, the source distribution and licensed fallback archives.
By default it retains only the small identity/manifest reports for three days, not
installable binaries. Cross-compilation is not native execution or release approval.

For one candidate intended for maintainer acceptance, explicitly select
`retain_installable`. This preserves the same checked wheels, sdist, native archives,
manifest, installation guide and a self-contained shallow Git repository for **one day**. It does
not rebuild, publish, update a channel or claim release approval. That repository contains
the candidate and its source parent, not unrelated history, checkout configuration or
untracked files. The final `handoff.json` records identity only after the copied
artifacts pass verification. An interrupted retention is not an accepted handoff.

This opt-in is a bounded exception to the contribution guideline against large CI
artifacts: approximately 400 MB per retained candidate. Keep it
off for routine preflight and schedules; assess storage before using it. Download and
preserve an approved handoff before the one-day expiry. Do not rebuild expired files
and reuse their old verification report. This workflow change requires that resource
exception to be called out explicitly in the PR before merge.

After assembly, the workflow installs the Linux x64 wheel and its binary dependencies
in a separate venv with no Bun/Node/Git on the install PATH. It then uses that venv's
isolated Python to check version/commit/import identity, serve every Vite-manifest asset
(including lazy chunks) through the installed asset handler on loopback, and execute
the bundled TUI's `--desktop-protocol` probe with downloads disabled and an empty private
HOME. With `--gateway`, the workflow also starts the installed CLI's foreground gateway
with a new, private profile, no configured provider/MCP servers, disabled heartbeat and
two loopback-only ports. It verifies readiness, the running version through the protected
WebUI identity endpoint, the actual HTML response, and process/listener cleanup. Unix
must exit gracefully; Windows cleanup uses process termination and is labelled as such,
not graceful-shutdown evidence. No model task or external channel is exercised.

The small report identifies its actual OS, CPU and which probes ran. This is native
package/startup verification, not interactive TUI/WebUI, updater-managed restart, migration,
public-download or five-platform E2E coverage.

The same check can run against a disposable native installation on another supported
platform; it neither installs nor changes the package being checked:

```bash
<installed-venv-python> -I scripts/verify_installed_release.py \
  --version <candidate-version> --commit <candidate-commit> \
  --gateway --report <new-report-path>
```

Use the prepared candidate commit, not its source parent. Reports are written only on
success and never replace earlier evidence. The probe rejects checkout imports and
unisolated invocation; it does not read the user's gateway configuration or credentials.
Omit `--gateway` to run only asset and native TUI probes. A failed startup writes no
success report and prints a bounded, secret-redacted log tail after cleaning up its child.

To reproduce preparation locally, use a full source SHA and a new output directory
outside the checkout. The example base/sequence are illustrative, not published versions:

```bash
python -m scripts.release_candidate prepare \
  --source-commit <full-commit-sha> --base 0.3.6 --sequence 42 \
  --output <new-candidate-directory>
```

This leaves the source checkout untouched and creates a candidate commit with only the
package and fallback version changes. Identical source/base/sequence inputs produce the
same candidate commit. Build Python distributions and all native targets from that
candidate using the commands above. Then, from its directory:

```bash
python -m scripts.release_candidate assemble --source-commit <original-source-sha> \
  --wheel <intermediates>/nanobot_ai-0.3.6.dev42-py3-none-any.whl \
  --sdist <intermediates>/nanobot_ai-0.3.6.dev42.tar.gz \
  --tui-dir tui/dist --output <new-artifact-directory>
```

Assembly refuses an existing output directory. It emits `release-manifest.json` only
after checking the complete set, version/commit identity, WebUI presence, wheel RECORDs,
native bundle/source correspondence and executable permissions. It also compares the
sdist's application sources/resources with the tracked candidate (using the packaging
exclusions), then requires every platform wheel to carry the same application and built
WebUI bytes as that sdist. A commit marker or a valid RECORD alone does not establish
that correspondence. This byte comparison does not prove reproducible frontend/native
compilation or replace the clean build and native execution gates. `verify --source-commit
<original-source-sha> --artifacts <artifact-directory>` rechecks the same candidate;
it may reuse an identical manifest but never overwrite one with different bytes.

Generate the installation handoff from that same candidate:

```bash
python -m scripts.release_candidate instructions --source-commit <original-source-sha> \
  --artifacts <artifact-directory> --output <new-install-guide-path.md>
```

This rechecks all artifacts against the candidate and retained manifest before writing
commands. The guide is a review report outside the immutable upload directory;
it cannot overwrite different earlier evidence. When both candidate installers match
the known implementation, it leads with macOS/Linux and Windows commands that download
the installer from that exact candidate commit and pass the retained manifest's SHA-256.
These select the platform automatically. Older candidates retain the manual handoff;
the generator never points them to a mutable `main` script or assumes support for new flags.
Publishing must also make the pinned installer source publicly reachable.

The guide includes the exact version, source and candidate commits, five platform wheels
with hash-bound URLs, and separate new/existing
base-package commands for uv, pipx and an ordinary pip venv. Users save the selected wheel
in a directory they own; the commands check its size and SHA-256 with the standard library
before passing that local file to the manager. Do not rely on a URL hash fragment alone:
the tested uv tool commands did not reject an incorrect fragment. Retain the saved wheel
because a manager may record its path. No new manifest schema or installer executable is
introduced. The manual commands are folded into an advanced section when the automatic
entry is available. CI retains this guide alongside the other small reports.

The guide is not publication approval or automatic channel selection. Before offering it
to users, publish and verify the exact public files and add the release-specific changes,
native coverage, migration and recovery instructions. Existing installs must be stopped
and backed up first; extras, suffixed/locked installs and external deployment owners need
their recorded options reviewed. A successful manager exit can mean a pinned package was
left unchanged: verify the persistent package and then the restarted gateway separately.
The real offline manager fixtures test command semantics, not gateway restart or migration.

The candidate clone borrows Git objects from its source repository. Preserve that
repository until the candidate is retained in an approved permanent ref; the temporary
clone is not a durable source archive by itself. Partial assembly has no accepted manifest
and must not be uploaded. Native launch, clean installation, upgrade/recovery, source-offer
commitment and the final publication procedure remain required gates. Existing TUI
publication now refuses to overwrite assets; recover missing uploads from the original
verified files instead of rebuilding and replacing a public release.

To retain the exact local handoff outside a temporary build checkout:

```bash
python -m scripts.release_candidate retain --source-commit <original-source-sha> \
  --artifacts <verified-artifact-directory> --output <new-retained-directory>
```

The `artifacts/` subdirectory is the only release upload set. `source.git/`,
`install.md` and `handoff.json` are maintenance handoff files, not additional PyPI
packages. Restore the source with `git clone --no-local <retained>/source.git <new-checkout>`
and check its HEAD against `handoff.json`. Re-run `release_candidate verify` against
the retained `artifacts/` before the separately approved publication. Keep native
test reports and release notes with the handoff; retention itself adds no native,
migration, interactive UI or public-download acceptance evidence.
