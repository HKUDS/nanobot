# Release checklist

Use this checklist with the [Release Packaging Contract](../CONTRIBUTING.md#release-packaging-contract). Preparing a release does not publish it. Pushing a Git tag, publishing a GitHub Release, uploading to PyPI, and deploying the documentation are separate operations.

## Release cadence

Use one product and two release feeds, not two separate interfaces. Stable is
the default; Preview is optional and easy to find in Settings → About. Both require
confirmation before installation. A faster release cadence never grants permission
to stop a user's tasks or restart their gateway automatically.

| Release | When to prepare it | Public destination | User experience |
| --- | --- | --- | --- |
| Stable feature release | At the planned feature milestone | Final GitHub Release and PyPI; also index its manifest for Preview subscribers | Normal update notice |
| Stable patch | When a reviewed fix or small, compatible improvement is ready; do not wait for the next monthly milestone | Same stable destinations and checks | Normal update notice, no Preview opt-in required |
| Preview | When a maintainer requests a candidate from reviewed changes with passing checks; it can be as frequent as daily | GitHub prerelease plus the protected `release-index` catalogue; not PyPI in this design | Same update notice, only for subscribers; risk shown before installation |

Packaging is maintainer-triggered: no nightly timer or push-triggered package build.
A request to prepare a candidate does not authorize publication. Record the requested
channel, exact source and candidate identity before acting; publish only with approval
for those verified artifacts. These policies do not promise a new version every day. An unchanged
source, failed check, missing platform asset, incomplete acceptance or absent
publication approval leaves the last verified release in place. Users can skip
intermediate previews. Release acceptance must cover upgrading from the supported
stable baseline and an earlier Preview, not only the immediately previous build.

### Stable patch procedure

1. Select the supported stable baseline and the reviewed fixes. If `main` contains
   unfinished features, prepare a release branch from that baseline and backport
   only the required fixes. Do not relabel an unverified Preview as stable.
2. Allocate an unused final version, update both version declarations, and follow
   **Prepare a candidate** below. Patch releases have the same package, licensing,
   native startup, data-preservation and update/recovery gates as feature releases.
   A small diff is not permission to skip those gates.
3. Publish the approved, immutable files in the order below: GitHub files, PyPI,
   public-download checks, then the catalogue's `stable` pointer. Keep the existing
   `preview` pointer and withdrawal history. Preview subscribers select the newer
   eligible version; a stable patch older than their installed Preview is not a
   downgrade offer.
4. Publish concise notes describing the fixes and any required operator action.
   Existing users who lack this updater still need the original installation method
   for their first upgrade. External package/deployment owners keep their own route.

### Maintainer-triggered Preview procedure

1. Select an exact, reviewed `main` commit whose required CI passed. Compare its
   source SHA with the last accepted candidate; skip an unchanged source. Record
   the next unreleased stable base and an unused increasing Preview sequence.
2. Run **Verify Release Candidate** for that exact ref and base. It creates a
   separate version-only candidate, builds the WebUI and five native TUI bundles,
   and verifies the full package set. Ordinary users install these built packages,
   not a source checkout that needs Bun. The workflow remains manual and read-only.
3. For a candidate intended for publication, explicitly retain its installable
   handoff and preserve it before expiry. Run the remaining native and packaged
   old-to-new update/recovery acceptance checks against those exact bytes. Keep
   candidate SHA, manifest hash, coverage, known issues and source-offer approval
   together. CI reports alone are not an installable release or publication consent.
4. With separate maintainer approval, publish an immutable `v<version>` tag at the
   **candidate** commit and a GitHub **prerelease**. Do not mark it as the latest
   stable release. Upload the complete verified artifact set and manifest, plus
   release notes. The pinned installer source must also be publicly reachable.
5. Check every public artifact's size/hash and run the clean public install/update
   acceptance. Only then advance the protected catalogue's `preview` pointer with
   a new generation. Validate it against the latest catalogue, preserve `stable`
   and all withdrawals, and serialize writes with stable publication/withdrawal.
   A stale publisher must reread and revalidate instead of overwriting a newer index.
6. On partial upload, keep the feed unchanged and resume only from the original
   verified files. If those bytes are lost or changed, allocate a new version and
   repeat acceptance. If a published candidate is unsafe, withdraw it with a reason
   and offer a newer fixed version; do not rewind the feed or restore user data.

Use `X.Y.Z.devN`, ordered by Python's version rules, not a display-date comparison.
For example, `0.3.6.dev42 < 0.3.6.dev43 < 0.3.6 < 0.3.7.dev1`. Examples are not
published versions. Once `0.3.6` ships, new previews need a later base; a stable
patch can consume a previously planned base, so allocate it before the next build.
The current workflow uses `github.run_number` for `N`; do not reset or replace that
sequence without checking published versions. Rerunning a job does not authorize
replacing files for the same version. A final release must be rebuilt, tested and
published under its own final identity; do not rename `.devN` wheels.

### Launch gates and automation boundary

This PR implements discovery, consent, update/recovery and manual candidate
preparation. It does **not** enable a cron schedule, a protected publisher, PyPI
uploads or a public Preview channel. Public Preview availability still needs maintainers
to approve index ownership/protection, publication credentials, source retention
and the exact packaged/public-download acceptance. The candidate workflow's
one-day installable retention is opt-in (~400 MB); do not turn it on for every
candidate build. Preserve approved release bytes and corresponding source
for their required lifetime outside expiring CI storage.

Automate the steps inside an explicitly requested run, not the decision to build or
publish. Keep build permissions read-only and publication permissions restricted to
a protected publication stage with the gates above. Record
the last accepted source/version and use one catalogue writer; retries must not
reuse a published version for different bytes. No schedule is activated here.
Announce Preview availability, including one dismissible discovery hint for existing
users if added, only after its public feed is verified. Do not show a blue update
badge for an unavailable channel or enroll stable users merely because they check.

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

### Protected updater handoff compatibility

Packages that support restarting a gateway through the standalone updater include
`nanobot/update_contract.json`. Its schema version 1 declares `handoff_protocols` as
a list of positive integer protocol IDs. The current implementation supports protocol
1: worker request schema 4, frozen `-I -S` startup with child-owned installation
leases, scoped data-startup grants, and activation bound to the exact restarted run.
This contract is separate from the package version and WebUI protocol.

Before publishing an update that advertises protocol 1, run the preparation, frozen
worker and actual-gateway restart tests against its packaged code. Verify the manifest
is included in both sdist and wheel. A declaration is not proof that a changed
implementation honors it. Retain a protocol only while its entire handoff contract
is supported; assign a new ID for incompatible request, startup or activation behavior.
An older updater may use a future package only if that package still supports its
protocol. Missing, malformed and non-overlapping declarations require the external
installation-owner update procedure; they must be refused before gateway shutdown.

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

Final releases also need `release-manifest.json` for the catalogue's `stable`
pointer. From the clean final-version checkout, `scripts.release_candidate assemble`
can build the complete upload set from the intermediate wheel, sdist and verified
TUI archives, using the final commit itself as `--source-commit` (no Preview
version preparation). See the assembly commands below. Upload these same five
wheels, sdist, ten native archive/checksum files and manifest to GitHub; upload
only the wheels and sdist to PyPI. Verify the manifest against the exact final
source and public bytes before advancing the catalogue. A TUI-only GitHub Release
cannot serve Preview subscribers a final release through this catalogue.

## Publish, with maintainer approval

### Release approval proof

Automatic installation requires `release-manifest.json.sigstore.json` beside the
manifest on the exact GitHub release, for **both Stable and Preview**. The client
verifies Sigstore's production certificate chain and transparency proof. It accepts
only the manual `release-approve.yml` workflow on `HKUDS/nanobot`'s `main` branch.
The signed manifest must match the selected version, wheel size and digest.
Preview also retains the catalogue's commit/manifest binding. This gate runs
before download and again before gateway shutdown. There is no unsigned fallback.

Before enabling signing, an administrator must protect `main` and the
`release-approval` environment: require independent review, prevent self-review,
restrict deployment branches to `main`, and restrict bypass and modifications to
the workflow and signing requirements. Only then set the repository variable
`NANOBOT_RELEASE_SIGNING_ENABLED=true`. Without this variable the workflow is
disabled. This PR does not create those settings or activate signing. No long-lived
signing key or Apple Developer ID is required.

After candidate tests and dependency review, obtain the version, manifest SHA-256,
source SHA and candidate SHA from retained acceptance evidence, **not** from
whatever the public download currently says. Upload the proposed manifest through
the normal separately authorized release handoff. Manually run **Approve Exact
Release** from `main` with those four values and obtain the environment review.
The job checks the exact manifest and signs it with hash-locked signing tools.
It does not install candidate code and cannot write releases, PyPI or the catalogue.
Attach the resulting proof to the release as a separate authorized publication
step. Verify it from the public endpoint before advancing either channel. Preserve
the proof with the candidate evidence; its workflow artifact expires after three days.

Regenerate the signing lock only in a reviewed dependency update:

```bash
uv pip compile .github/release-signing-requirements.in --python-version 3.11 \
  --python-platform x86_64-manylinux_2_17 --generate-hashes --no-header \
  --output-file .github/release-signing-requirements.txt
```

Review the resolved changes; generating hashes is not malware review. This is an
intentional publication prerequisite, not a data migration or recovery protocol
change. Unsigned historical releases remain discoverable but cannot be automatically
installed by this verifier. Existing installations keep running. Before first
release, prove that a supported real old updater can install the signed candidate
and that the candidate can install the next signed version. Private packaged
recovery fixtures substitute publication authority and are not signature evidence.

The proof authenticates **release approval**, not reproducible-build provenance or
the absence of malicious code. A compromised authorized workflow/reviewer, malicious
source that passes review, and compromised runtime dependencies remain trust risks.
The signing-tool lock does **not** lock users' runtime dependency graphs. Runtime
resolution retains the installation owner's supported policy. A reviewed runtime
dependency inventory, public signed upgrade continuity and verified repository
protection settings remain security-release gates. Do not advertise comprehensive
supply-chain protection before these are complete. The first installer and its
checksum source also require a trusted distribution channel.

1. Confirm all pre-tag gates above are complete. Create and push exactly `vX.Y.Z`; do not move or reuse a published version tag.
2. Create the matching GitHub Release. A draft may be used while assembling its attachments. Pushing the tag alone does not run `Publish Terminal UI` or upload anything to PyPI.
3. Attach the complete verified set: five platform wheels, sdist, five TUI archives, their `.sha256` files and `release-manifest.json`, after confirming the tag's packaged sources match the manifest. Complete the release approval proof handoff above before offering automatic updates. Verify the uploaded bytes match their preflight hashes; never upload a naked executable.
4. If instead rebuilding the native archives through **Publish Terminal UI**, use `tag=vX.Y.Z` and confirm the already completed compliance review. Wait for all five targets and repeat artifact checks on those new outputs. Assemble and recheck the platform wheels and manifest using those exact archives before uploading the remaining files. Do not combine new archives with old embedded wheel bytes or hashes. If this would replace an already-public asset, allocate a new version instead.
5. Make the GitHub Release and the complete artifact set publicly available. Verify every public file against the accepted manifest, including the native archives for fallback/source-built installations. Supported platform-wheel installs do not need archive downloads to start the TUI.
6. Upload only the checked `nanobot_ai-X.Y.Z.tar.gz` and the five final platform wheels to PyPI. Do not upload the intermediate universal wheel or stale files from a shared `dist/` directory. This repository has no automatic PyPI publication workflow.
7. Verify installation from PyPI, bundled WebUI startup, and bundled TUI startup without downloads in clean environments. After all public GitHub/PyPI files pass, advance the protected catalogue's `stable` pointer to this manifest, retaining Preview and withdrawal history. Verify discovery for both subscriptions. Merge the prepared wiki PR only when the stable package is available: merging its `main` deploys the site automatically. Confirm all localized `/docs/latest/` routes select the new version and old version links still work.
8. Publish the release announcement and add the dated entry to [Release Archive](./release-archive.md). Complete any coordinated advisory publication and reporter notification. Record links and completion status in the release tracking issue.

## If a gate fails

Do not publish to PyPI while a required TUI artifact or verification is missing. Keep the documentation's public `latest` on the previous stable version until the new version is usable. If a published package needs a correction, prepare a new version; do not silently replace the code behind an existing release tag. Stop all old processes and follow the documented session rollback procedure before downgrading a migrated installation.

## Installer identity checks

Fresh installs now use the official installer's dedicated venv regardless of which
optional manager is on PATH. A new base-package selection gets `nanobot-install.json`
before venv/download work, so a failed first installation can be retried without
losing its owner. The receipt alone does not prove installed/readiness state.
Existing venvs/uv/pipx are never adopted or moved. This is an
intentional default change for new installations, not a migration of old users.
The receipt opts `webui` into persistent background launch and records the extras
used by the in-app update planner. Unrecorded installs keep their previous lifecycle.
Mention this and the instance-specific stop command in release notes.

The Linux/Windows native CI jobs build the native platform wheel, invoke the actual
public installer with a verified wheel in a private home without Bun/Node/Git on
PATH, require the fresh managed receipt, then probe installed WebUI assets, native
TUI and the running gateway. Only small reports are retained; no candidate binaries
are uploaded by these PR checks. The job runs for Python/WebUI changes too, because
a working native executable alone is not packaged-application acceptance. These
checks complement the real offline interrupted-install/recovery tests; they are
not five-platform native E2E or public-download evidence.

The release gate also requires an actual packaged old-to-new update with disposable
configuration and sessions, retained backup and verified restarted version. Record
which OS ran that journey separately from installer fixtures and startup probes.
Do not call a skipped platform or a structurally valid cross-build a native pass.

### Packaged upgrade and recovery acceptance

The Linux and Windows native CI jobs also run `scripts/verify_packaged_update.py`
against the same native wheel. The manual candidate workflow runs it against the
assembled Linux wheel. Run it locally on macOS against that candidate's macOS wheel:

```bash
<build-tools-python> -I scripts/verify_packaged_update.py \
  --wheel <exact-native-wheel> --commit <candidate-commit> \
  --output <new-private-acceptance-directory>
```

The build-tools environment needs the project's Python dependencies. The probe
creates a separate venv, account, configuration, workspace and loopback gateways.
It does not use the maintainer's configuration, chat records, model or credentials.
The healthy target is not rewritten. The report records its SHA-256 and candidate
commit. Faulted targets are separate private files and must never be uploaded.

The journeys cover normal upgrade, consecutive upgrades, an earlier Preview, candidate import/startup
failure, backup-write failure after shutdown, worker termination, partial package
metadata loss, and interruption between the program-restoration renames. Each
successful journey requires the expected running version, a new gateway run,
authenticated history reads, continued writes and a second ordinary start. The
probe compares configuration and retained legacy-source bytes, canonical SQLite
records and WebUI transcripts separately. Every restored service then performs a
fresh update to the healthy target with the same account and conversations. The
consecutive-upgrade case uses an explicitly instrumented intermediate Preview;
its second hop installs the unchanged final wheel. Faults are scoped to the first
job in each account; backup failure persists across that job's automatic retry,
while a separately confirmed next update can prepare a healthy backup.
It seeds canonical-only, display-only
and mixed history; it does not invent canonical records for display-only chats.
SQLite checkpoint byte changes alone are not data loss. The journeys also cover
pending scheduled-delivery records in `delivery/outbox.sqlite3`.
Its runtime owner must remain inactive during protected startup and maintenance.
The original protocol-1 store grant remains accepted without changing its scope;
the new, lazy delivery store holds a separate ordinary lease for its lifetime,
with writes deferred until activation.
The new restart coordinator must derive its grant from the reviewed old scope,
not implicitly expand it by recomputing the latest store inventory. The real
parked-gateway regression exercises both inventories through activation.
Current updaters include the store in their full backup and reservation. This
compatibility path does not permit initialization or migration outside an old grant.
Only small reports are
retained in CI, including completed per-case reports if a later case fails. The
aggregate success report is written only after every selected journey passes;
partial case reports and a timed-out job are not an overall pass.

These are real installed-process journeys with controlled release transport and
explicit fault injection, not public-download or interactive browser evidence.
Until a public updater-enabled baseline exists, the default earlier versions are
clearly labelled fixtures made from the target application. They test the installed
transaction but do not prove compatibility with historical release code. For a
release handoff, also pass `--baseline-wheel <previously-accepted-wheel>` and repeat
with the supported stable baseline and an older Preview, including a skipped
Preview. The baseline's feed transport is instrumented; the healthy target remains
unchanged. A retained pre-SQLite updater package also exercises JSONL-to-SQLite
migration: check canonical message bodies as well as the separate display history.
When a fault restores that historical JSONL runtime, SQLite checks are marked not
applicable, not reported as a SQLite pass. Versions without this updater use the
original install owner's bootstrap upgrade, not an invented in-app upgrade.
Record that acceptance separately.

For installation-owner acceptance, run consecutive updates in the same disposable
account and keep its existing conversations. Exercise the applicable official
installer, uv tool, pipx, ordinary pip venv and source routes, not a different manager
that happens to succeed. Check recorded constraints/options before and after, use
the guidance's actual command where offered, verify the restarted gateway, append a
message and repeat an ordinary start. A policy refusal must leave the original
installation unchanged; an owner-reviewed custom update is separate evidence, not
an automatic-recovery claim. Container replacement must retain its data volumes and
needs a real container engine; a mocked container marker is not that acceptance.

Keep the private evidence directory until the reports are reviewed. It can contain
retained program generations and disposable backup data; it is not a release upload
set. Native execution on Linux x64, Windows x64 and macOS arm64 does not establish
native macOS x64 or Linux arm64 coverage. Those targets and the final public download
still need their own acceptance before claiming that coverage.

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
environment must be updated through its manager instead of pip. uv keeps its existing
constraints, so a pinned installation can stay at its pinned version. Generic pipx
upgrades can drop version constraints and pip options. The installer refuses pipx
records with those settings, a lock workflow or an unconfirmed source; the owner must
review and preserve them. An explicit wheel handoff may replace a previous wheel
source, but does not override registry constraints or custom pip options.

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

## Stable and Preview subscriptions

Settings → About keeps one update flow. **Receive preview updates** is directly
visible below the check/update area, without an extra disclosure or separate mode.
It is off by default even on an existing development build: a version string is
not opt-in consent. Preview may contain regressions.
Changing the switch saves a subscription and checks its feed; it does not download,
install, stop tasks or restart a gateway. Updating still requires a separate
exact-version review and confirmation, with a warning for a Preview target.
Turning the switch off waits for a newer final release; it never downgrades.

The gateway stores the preference and a revision under the current OS account's
installation state directory (`~/.nanobot/updates/<environment-id>/channel.json`).
Profiles sharing that Python environment share the subscription; another installation
or account does not. Moving/replacing the environment can change its identity and
requires selecting the channel again. Browser storage is not the source of truth.

| Current install / requested channel | Behavior |
| --- | --- |
| Stable → Preview, a newer verified preview exists | Offer that exact preview; install only after confirmation. |
| Preview → Preview | Offer only a higher verified version, including a final release. |
| Preview → Stable, stable is newer | Offer the final release; keep Stable selected. |
| Preview → Stable, stable is older | Save Stable and wait for a newer final release; keep running the preview. |
| Preview subscriber installs a final release | Keep Preview selected for the next development cycle. |
| Current preview was withdrawn | Show a warning, including when no safe newer replacement exists; never silently downgrade. |
| Feed offline, incomplete, missing or incompatible | Show a non-success result; keep the subscription and allow another check. |

The stable checker and planner both require the complete PyPI wheel/sdist upload.
Preview uses `release-index/catalogue.json` and exact GitHub release manifests, not
PyPI `--pre` or an arbitrary Git branch. A channel's candidate is validated against
the gateway's interpreter/platform, not the browser's device. The latest final release
must also be indexed so Preview subscribers receive it. Advance the catalogue only
after all referenced public assets are verified. Versions/tags/manifest hashes must
be immutable; increment generation on changes, never rewind pointers or remove a
withdrawal to reuse a bad version. Once published, a pointer cannot be cleared:
retain it and withdraw its version to stop offering it. This preserves the observed
version history even when a channel temporarily has no eligible release. Validate
proposed metadata with
`ReleaseCatalogue.validate_successor(previous)` before publication. Clients reject
rewrites relative to their last accepted catalogue; this is not cryptographic signing.

Changing channels invalidates old reviews, including Stable → Preview → Stable.
Inactive staged work is cancelled through the normal worker/stop checks and retained
for diagnosis. Active preparation, committed shutdown, admitted installation or a
failed mutation blocks switching until settled/recovered. Stale tabs cannot overwrite
newer selections. Lost responses are followed by a fresh read, never an automatic
installation retry. Installer-owned background gateways have a frozen, independent
recovery supervisor: one exact-target repair, then verified original-program
restoration only before activation and only if protected data is unchanged. It
restarts and checks the reviewed service without browser or terminal intervention.
Other installation owners keep their existing repair route. Do not delete the job,
clear its fence, or automatically restore old configuration/chat data. An older
package may not understand new persisted data.

Release acceptance must exercise both a healthy packaged upgrade and injected
candidate import/startup failure, backup failure after shutdown, worker termination,
and interruption between the journaled program renames. Verify real gateway health,
version, authenticated history reads, continued writes and a second start; compare
configuration and existing conversation bytes. Also prove that data changes,
activation, live owners and changed installation ownership prevent unsafe rollback.
Run native Windows checks for file-lock/rename behavior, not only POSIX mocks. Loss
of both supervisor and worker, permanent storage damage and incompatible data writes
are not claimed to recover automatically. Keep these limits in release notes and
the operator guide; a green unit suite alone is not packaged release acceptance.

Channel discovery does not expand installation authority: the official managed venv
and supported POSIX uv transactions retain their reviewed stop/install/restart flow;
pipx, source, container, system-managed, unsupported uv/platform configurations and
native desktop distributions retain their installation-owner/distributor path. Remote
browsers without explicit package-install permission may read channel status but
cannot change the subscription. Enabling Preview does not grant that permission. Older
clients use the legacy check response; statuses they cannot represent return an
actionable failure instead of a false green “up to date.”

`nanobot update --plan` inspects the saved subscription; `--plan --channel stable`
or `--plan --channel preview` is a one-time inspection, not a subscription change.
The legacy `nanobot update` / `--check` commands still target stable PyPI releases,
and `--dev` means an editable source checkout, not Preview. Use Settings → About
for channel-aware confirmation/restart. External package-manager commands do not
read nanobot's subscription, so their channel/version selection remains explicit.

**This PR does not launch a public Preview channel.** Publication still needs maintainer
approval, protected index ownership, complete verified release assets and a successful
clean public install/update/recovery check. No daily schedule or public release is
enabled by the selector or by the preflight workflow below.

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
