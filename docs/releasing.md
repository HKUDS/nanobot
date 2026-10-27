# Release checklist

Use this checklist with the [Release Packaging Contract](../CONTRIBUTING.md#release-packaging-contract). Preparation does not authorize publication. Pushing tags, publishing GitHub Releases, uploading to PyPI and deploying documentation are separate operations.

## Release cadence

Stable is the default feed; Preview is opt-in. Both use one update flow and require confirmation before installation. Neither a faster cadence nor a subscription permits stopping tasks or restarting a gateway automatically. See [Updating nanobot](./updating.md) for user instructions.

| Release | When to prepare it | Public destination | User experience |
| --- | --- | --- | --- |
| Stable feature release | At the planned feature milestone | Final GitHub Release and PyPI; also index its manifest for Preview subscribers | Normal update notice |
| Stable patch | When a reviewed fix or small, compatible improvement is ready; do not wait for the next monthly milestone | Same stable destinations and checks | Normal update notice, no Preview opt-in required |
| Preview | On maintainer request, from reviewed changes with passing checks; potentially daily | GitHub prerelease and protected `release-index` catalogue; not PyPI | Same update notice for subscribers, with risk shown before installation |

Packaging is maintainer-triggered, not scheduled or push-triggered. Record the requested channel, exact source and candidate identity; preparation does not authorize publication. Unchanged source, failed checks, missing assets, incomplete acceptance or absent approval leaves the last verified release in place. There is no daily-release promise. Acceptance must cover the supported stable baseline and an earlier Preview, including skipped previews, not just the previous build.

### Stable patch procedure

1. Select the supported stable baseline and reviewed fixes. If `main` contains unfinished features, branch from that baseline and backport only the required fixes. Do not relabel an unverified Preview as stable.
2. Allocate an unused final version, update both version declarations, and follow **Prepare a candidate**. Patches require the same packaging, licensing, native startup, data-preservation and update/recovery gates as feature releases.
3. Publish approved immutable files in order: GitHub, PyPI, public-download checks, then the catalogue's `stable` pointer. Preserve `preview` and withdrawal history. A stable patch older than an installed Preview must not be offered as a downgrade.
4. Publish concise fix notes and required operator actions. Users without this updater need their original installation method for the first upgrade; external package/deployment owners retain their route.

### Maintainer-triggered Preview procedure

1. Select an exact reviewed `main` commit with passing required CI; skip it if its source SHA matches the last accepted candidate. Record the next unreleased stable base and an unused increasing Preview sequence.
2. Run **Verify Release Candidate** for that ref and base. It prepares a version-only candidate, builds the WebUI and five native TUI bundles once, and runs Linux x64 and Windows x64 clean-install and packaged update/recovery acceptance against the exact manifest-bound wheels without publication. Require the **Candidate required** check to pass; build-only reports are insufficient. Users receive built packages, not a checkout requiring Bun.
3. Select `retain_installable` and preserve the accepted `installable-candidate` handoff before expiry. Temporary `candidate-native` inputs and `prepared-candidate` artifacts are not accepted handoffs. Complete the remaining native-platform and real historical-baseline acceptance against those exact bytes; the automated fault-injection fixtures do not establish compatibility with a previously published version. Keep candidate SHA, manifest hash, coverage, known issues and source-offer approval together; CI reports alone are neither installable artifacts nor publication consent.
4. With separate approval, publish immutable `v<version>` at the **candidate** commit and a GitHub prerelease, never the latest stable release. Upload the complete verified set, manifest and notes; make the pinned installer source publicly reachable.
5. Verify all public sizes/hashes and clean public install/update acceptance before advancing `preview` with a new catalogue generation. Validate against the latest catalogue, preserve `stable` and withdrawals, and serialize stable, Preview and withdrawal writes. A stale publisher must reread and revalidate.
6. After partial upload, leave the feed unchanged and resume only from the original verified files. Lost or changed bytes require a new version and repeated acceptance. Withdraw unsafe candidates with a reason and offer a newer fix; never rewind the feed or restore user data.

Use Python version ordering: `0.3.6.dev42 < 0.3.6.dev43 < 0.3.6 < 0.3.7.dev1` (illustrative versions). Once a final base ships, previews need a later base; allocate it after accounting for stable patches. The workflow uses `github.run_number` for `N` in `X.Y.Z.devN`; do not reset the sequence without checking published versions. Reruns cannot replace published bytes. Rebuild and test final releases under their final identity; never rename `.devN` wheels.

### Launch gates and automation boundary

Before offering public Preview, obtain approval for index ownership/protection, publication credentials, source retention and exact packaged/public-download acceptance. Candidate preparation does not activate a public channel, schedule, protected publisher or PyPI upload. Preserve approved release bytes and source outside expiring CI storage for their required lifetime.

Automate steps within an explicitly requested run, not the decision to build or publish. Keep builds read-only, publication permissions in a protected stage, the last accepted source/version recorded and one serialized catalogue writer. Announce Preview availability only after verifying its public feed. Any discovery hint must be dismissible; do not show an update badge for an unavailable channel or enroll users merely because they check.

## Prepare a candidate

1. Choose the previous release and exact candidate commit. Use a clean worktree without local configuration, sessions, credentials or unrelated changes.
2. Update `project.version` in `pyproject.toml` and the final source-only fallback in `nanobot/__init__.py`. Private WebUI/TUI versions are not the Python release version.
3. Review the final tag range; prepare highlights, upgrade/rollback guidance, acknowledgements and full changelog. Verify counts: commits are not merged PRs. Coordinate security disclosures separately.
4. Run Python, WebUI and TUI CI checks against the final commit, not an earlier PR head. Review installation, configuration, session and API changes.
5. Run `uv build --out-dir <artifact-directory>` in a clean output directory without `NANOBOT_SKIP_WEBUI_BUILD`. The build hook bundles WebUI in sdist and wheel; the wheel is built from the sdist.
6. Run `twine check` on intermediates, inspect contents and record SHA-256 hashes. Test installation in an isolated environment outside the checkout and upgrade from previous stable with disposable configuration/sessions, never a maintainer's live workspace.
7. Prepare the documentation PR in `Re-bin/nanobot-web` under its `MAINTAINING.md`: review English and all nine translations, preserve Nightly and previous releases, update latest-version redirects and run the full site quality gate. Pin source links to the candidate and confirm they match the eventual tag. Do not advertise an unpublished version.
8. Review pinned Bun/OpenTUI licenses, corresponding source and relinking instructions. Check upstream revision availability and runtime/lockfile/notice agreement. Obtain the maintainer's commitment to the [source offer](../tui/SOURCE_OFFER.md) for its full stated period, at least three years after release; tests cannot grant it.
9. Build all five native targets with publication scripts, ad-hoc signing macOS before packaging.
   - Verify archive checksums, manifests, architecture, licenses/notices and embedded source, including checkout-matching bytes for `tui/scripts/targets.ts` and `tui/scripts/target-bindings.ts`. Run supported native smoke tests, record coverage and exact-head CI evidence, and label cross-compiled-only targets.
   - Build platform wheels below, check them with `twine check`, validate RECORDs/tags/permissions and test pip selection on all five platforms.
   - Test first launch with an empty cache and `NANOBOT_TUI_NO_DOWNLOAD=1`; the executable must come from `site-packages/nanobot/tui/bin/`, not checkout or cache.
10. Merge release preparation only after current checks/reviews pass. Compare the merged source tree with the tested candidate; rebuild/recheck changes. Reconcile changelog and documentation links, then tag the verified commit, not an unchecked later `main` tip.

### Protected updater handoff compatibility

Restart-capable packages include `nanobot/update_contract.json`: schema version 1, with `handoff_protocols` listing positive integer protocol IDs. Protocol 1's request, protected startup and activation requirements are defined in the [update protocol](./update-protocol.md), independently of package and WebUI versions.

Before advertising protocol 1, run preparation, frozen-worker and actual-gateway restart tests against packaged code; verify the declaration is in both sdist and wheel. Retain an ID only while its entire contract is supported; incompatible request, startup or activation behavior needs a new ID. Older updaters may install a future package only if protocols overlap. Missing, malformed or non-overlapping declarations must be refused before shutdown and require the installation owner's external update route.

### OpenAI API selector compatibility window

The temporary `providers.openai.apiType` / `api_type` conversion lasts exactly two consecutive releases: the first containing `nanobot/config/provider_api_migration.py` and the next. Record the first and final supported tags in release notes. Config saves write `api`; there is no legacy runtime selector.

Before the third release, remove `provider_api_migration.py`, its import, `ProvidersConfig._migrate_legacy_api_type`, the legacy settings query conversion in `nanobot/webui/settings_models.py` and migration-specific tests. Update configuration docs and release notes to require the current format. Keep current-format routing, settings and persistence regressions.

### TUI preflight without a release tag

Use Bun 1.3.13 and a clean checkout; no tag or GitHub Release is required. Use the same `<target>` for preparation, compilation and notice generation. Run targets sequentially because preparation updates shared `node_modules`:

```bash
cd tui
bun install --frozen-lockfile
bun scripts/prepare-target.ts <target>
bun run build -- <target>
# For darwin-* only: ad-hoc sign dist/nanobot-tui-<target> before the next steps.
bun scripts/release-notices.ts <target>
python3 scripts/package-release.py <target>
```

Repeat for `darwin-arm64`, `darwin-x64`, `linux-arm64`, `linux-x64` and `win32-x64`. On macOS, run `codesign --force --sign - <binary>` and verify it; the publication workflow uses pinned `rcodesign` on Linux. Keep the ten `.zip`/`.zip.sha256` files with Python intermediates and provenance manifest in a candidate-specific directory, excluding configuration, backups and test environments from upload selections.

Candidate builds bundle minified JavaScript and the standalone Bun runtime with the additional precompiled bytecode cache disabled. Linux targets include both GNU and musl native variants, and x64 retains Bun's baseline CPU variant. Builds enforce a 135 MiB executable budget on Windows/Linux x64; other targets retain the existing 150 MiB ceiling until measured. The `dist/<executable>.size.json` report identifies the compiled, pre-signing executable and expected native packages; final archive manifests identify signed release bytes.

Before release, measure TUI first-screen and Mermaid render latency on each supported target, including first and warm renders. Verify cancellation and worker restart. Retain latency distributions and record executable, ZIP and final platform-wheel sizes separately. Cross-compilation and startup probes do not replace native interactive acceptance.

### Build the PyPI platform wheels

After `uv build` and native archive checks, from the exact release checkout:

```bash
uv run python -m scripts.build_tui_wheels \
  --wheel <intermediates>/nanobot_ai-X.Y.Z-py3-none-any.whl \
  --tui-dir <verified-tui-archives> \
  --out-dir <final-wheels>
```

The script checks Python version/RECORD and native checksums, architecture, notices and source against the checkout, then writes five bundled wheels with regenerated RECORDs. It refuses existing candidates; `--target <target>` selects one platform. Minimum tags are macOS 13, manylinux glibc 2.17 and Windows x64; x64 uses Bun's baseline SSE4.2 runtime, not AVX2. Recheck Bun/OpenTUI requirements when upgrading either. There are no musl or Windows ARM64 wheels; tags do not substitute for native execution.

PyPI receives **five platform wheels and one sdist**, not the intermediate universal wheel or native ZIPs. Keep the same build's platform-neutral sdist for Python/classic and WebUI on other platforms. Record source commit, version, files, hashes, checks and remaining gates; source changes require rebuilding and rechecking.

Final releases also require `release-manifest.json` for `stable`. Run `scripts.release_candidate assemble` as shown below from the clean final-version checkout, using that final commit as `--source-commit` without Preview preparation. GitHub receives the same wheels/sdist, ten archive/checksum files and manifest; PyPI receives only wheels/sdist. Verify final source and public bytes before catalogue advancement. A TUI-only GitHub Release cannot deliver the final release to Preview subscribers.

For the same-build Linux and Windows candidate acceptance, run **Verify Release Candidate** at the exact final-version ref with `channel=stable`, `next_stable` equal to that declared version and `retain_installable=true`. Stable preparation copies the exact commit without changing version declarations or creating a Preview commit; it rejects mismatched versions and existing stable tags. The default `channel=preview` retains the version-only Preview preparation. Both modes are read-only preparation, require **Candidate required** and retain accepted files for one day; neither publishes a tag, release, PyPI package or feed. Download and independently preserve the accepted handoff before expiry, then complete native macOS and historical-owner acceptance against that same manifest.

## Publish, with maintainer approval

### Release approval proof

Both Stable and Preview automatic installs require `release-manifest.json.sigstore.json` beside the manifest on the exact GitHub release. Clients verify Sigstore's production certificate chain/transparency proof and accept only `HKUDS/nanobot`'s manual `release-approve.yml` on `main`. The signed manifest must match version, wheel size/digest and, for Preview, catalogue commit/manifest binding. Verification runs before download and before shutdown, with no unsigned fallback. Unsigned historical releases remain discoverable but cannot be automatically installed; existing installations keep running.

Before setting the repository variable `NANOBOT_RELEASE_SIGNING_ENABLED=true`, an administrator must protect `main` and the `release-approval` environment: require independent review, prevent self-review, allow deployment only from `main`, and restrict bypass and changes to the workflow/signing requirements. Signing is disabled without that variable. No long-lived signing key or Apple Developer ID is required.

After candidate tests and dependency review, take version, manifest SHA-256, source SHA and candidate SHA from retained acceptance evidence, not public downloads. Upload the proposed manifest through the separately authorized release handoff, then manually run **Approve Exact Release** from `main` with those values and obtain environment review. The hash-locked job checks/signs the exact manifest without installing candidate code or writing releases, PyPI or the catalogue. Separately authorize attaching its proof, verify the public proof before advancing either channel, and preserve it with candidate evidence before its three-day CI expiry.

Regenerate the signing lock only in a reviewed dependency update:

```bash
uv pip compile .github/release-signing-requirements.in --python-version 3.11 \
  --python-platform x86_64-manylinux_2_17 --generate-hashes --no-header \
  --output-file .github/release-signing-requirements.txt
```

Review resolved dependencies; hashes are not malware review. Before the first release, prove a supported real old updater can install the signed candidate and that the candidate can install the next signed version. Private packaged recovery fixtures substitute publication authority and are not signature evidence.

The proof authenticates release approval, not reproducible builds or harmless code. Compromised authorized workflows/reviewers, malicious source that passes review and compromised runtime dependencies remain risks. The signing lock does not lock runtime resolution, which retains the installation owner's policy. A reviewed runtime dependency inventory, public signed upgrade continuity and verified repository protection settings remain security-release gates; do not claim comprehensive supply-chain protection without them. The first installer and checksum source also need a trusted distribution channel.

1. Complete pre-tag gates, then create and push exactly `vX.Y.Z`; never move or reuse a published tag.
2. Create the matching GitHub Release. A tag push alone runs neither **Publish Terminal UI** nor PyPI publication.
3. Attach five platform wheels, sdist, five TUI archives, their `.sha256` files and `release-manifest.json`. Confirm tag sources match the manifest and uploaded hashes match preflight. Complete approval proof before offering automatic updates; never upload a naked executable.
4. If rebuilding via **Publish Terminal UI**, use `tag=vX.Y.Z` with compliance review confirmed. Wait for all five targets, recheck outputs, and assemble/recheck wheels and manifest from those exact archives. Never mix rebuilt archives with old wheel bytes/hashes; replacing public assets requires a new version.
5. Make the release and complete artifact set public. Verify every file against the accepted manifest, including native fallback/source-install archives. Platform-wheel TUI startup must not need downloads.
6. Upload only the checked `nanobot_ai-X.Y.Z.tar.gz` and five final wheels to PyPI, not the universal intermediate or stale shared `dist/` files. There is no automatic PyPI publication workflow.
7. Verify clean PyPI installation, bundled WebUI and download-free TUI startup. After all public GitHub/PyPI files pass, advance `stable`, preserving Preview and withdrawals; check discovery for both subscriptions. Only then merge the wiki PR: its `main` deploys automatically. Confirm all localized `/docs/latest/` routes select the new version and old-version links still work.
8. Announce the release, add its dated [Release Archive](./release-archive.md) entry, complete coordinated advisories/reporter notifications, and record links/status in the release tracking issue.

## If a gate fails

Do not publish to PyPI with missing TUI artifacts or verification. Keep public documentation's `latest` on the usable stable version. Correct published packages with a new version, never replacement code behind an existing tag. Before downgrading a migrated installation, stop all old processes and follow the documented session rollback procedure.

## Installer identity checks

Fresh base-package installs use the official installer's dedicated venv regardless of optional managers on PATH. `nanobot-install.json` is written before venv/download work so failed first installs retain their owner; it is not readiness proof. Existing venv/uv/pipx installations are not adopted or moved. The receipt records extras for update planning and opts `webui` into persistent background launch; unrecorded installs retain their lifecycle. Include this distinction and the instance-specific stop command in release notes.

Linux/Windows native CI builds a platform wheel and runs the public installer in a private home without Bun/Node/Git on PATH, then checks the managed receipt, installed WebUI, native TUI and gateway. Python/WebUI changes also require these jobs. CI retains small reports, not candidate binaries. Startup probes and offline installer fixtures do not replace packaged upgrade/recovery or public-download acceptance.

Run `pytest tests/test_install_scripts.py` with `uv` and `pipx` available. It uses private homes, offline fixture wheels and real managers, without a gateway or real application install: `install.sh` on Unix and Windows PowerShell with `install.ps1` on Windows. CI provisions pipx outside application dependencies. Verify these owner-preservation requirements:

- Launch the selected persistent environment's isolated Python, not `pipx run`, disposable tools or an arbitrary PATH executable. Existing recognized installations take priority over newly available managers; multiple recognized installs require explicit choice. An ordinary active venv is explicit; uv/pipx environments must use their manager.
- Preserve uv constraints. Generic pipx upgrades can drop constraints/options; the installer must refuse pipx records with those settings, lock workflows or unconfirmed sources. The owner must review and preserve them. Exact wheels may replace a wheel source, not registry constraints/options; pipx upgrades must retain requested extras and refuse wheels missing recorded extras.
- A failed selected manager must not fall through to another installation, even on first install. Verify the exact persistent package version before onboarding: a successful pinned/locked skip is not target installation. Restarted gateway identity is a separate check.

Verify the exact-handoff options against the pinned installer, not an older script: `install.sh --wheel <path> --sha256 <published-hash>` / `install.ps1 -Wheel <path> -Sha256 <published-hash>`, or `install.sh --release <version> --manifest-sha256 <trusted-manifest-hash>` / `install.ps1 -Release <version> -ManifestSha256 <trusted-manifest-hash>`. Wheel mode verifies checksum/package/version; release mode selects one of five native tags for the target Python and verifies size/hash/identity before invoking the original owner. No frontend toolchain or extra selector package is installed; the manager still checks Python/dependencies. Hashes must come from trusted metadata, not an unknown publisher.

Release downloads use official GitHub HTTPS hosts and configured HTTPS proxy; retain wheel sources at their recorded paths, including `~/.nanobot/downloads/releases` or `NANOBOT_RELEASE_CACHE`. Failed partial downloads are removed. Wheel-mode `--dry-run` / `-DryRun` verifies without installation/setup; release-mode dry-run checks only the manifest, creating no wheel/cache/environment/setup and proving neither wheel bytes nor dependency resolution.

These exact-version handoffs do not discover Preview, change subscriptions, stop gateways or back up data. Require stopped writers and backup first. Review extras and recorded options for plain pip, suffixed/custom installs and external owners; see the [user guide](./updating.md) and [update protocol](./update-protocol.md). Installer fixtures alone do not establish live maintenance, backup or restart safety.

### Packaged upgrade and recovery acceptance

Linux/Windows native CI runs `scripts/verify_packaged_update.py` against its wheel; manual candidate preparation uses the assembled Linux wheel. Run macOS acceptance against the candidate's macOS wheel:

```bash
<build-tools-python> -I scripts/verify_packaged_update.py \
  --wheel <exact-native-wheel> --commit <candidate-commit> \
  --output <new-private-acceptance-directory>
```

Build tools need project Python dependencies. The probe creates disposable venv/account/configuration/workspace and loopback gateways, without maintainer data, models or credentials. It records the unchanged healthy target's SHA-256 and candidate commit; faulted private wheels must never be uploaded.

On a local macOS desktop, add `--dock` to verify the real AppKit helper alongside these journeys. The managed receipt must make `nanobot webui --yes --no-open` detach automatically; each applicable running version must have one helper, preserve desktop intent through upgrade/recovery and a second start, and remove its helper on stop. Historical packages without Dock support gain the icon only after their first healthy upgrade and an explicit WebUI launch. This is process/lifecycle acceptance, not a visual Dock-click test; do not enable it on headless CI or claim native Windows/Linux icon coverage.

Require normal and consecutive upgrades, skipped Preview, import/startup failure, backup failure after shutdown, worker termination, partial metadata loss and interruption between program-restoration renames. Each successful journey must show the expected version in a new gateway run, a retained verified backup, authenticated history reads, continued writes and a second ordinary start. Each recovered service must then update to the healthy target with the same account/conversations. Faults affect the first job; backup failure must survive its automatic retry, while a separately confirmed next update can make a healthy backup. The instrumented intermediate Preview's second hop installs the unchanged final wheel.

Compare configuration, retained legacy-source bytes, canonical SQLite records, WebUI transcripts and pending `delivery/outbox.sqlite3` records separately. Cover canonical-only, display-only and mixed history without inventing canonical records for display-only chats; SQLite checkpoint byte changes alone are not data loss. Retain the protocol-1 parked-gateway regression across old/new protected-store inventories: no outbox initialization, migration or writes outside the old grant before activation. See the [update protocol](./update-protocol.md) for scope and lease requirements.

Default baselines are labelled target-derived fixtures, not historical compatibility evidence. For release acceptance, add `--baseline-wheel <previously-accepted-wheel>` and repeat with supported stable and older Preview packages, including skipped Preview. Baseline feed transport is instrumented; the healthy target is unchanged. Include a retained pre-SQLite updater to check JSONL migration's canonical message bodies separately from display history. If recovery restores JSONL code, mark SQLite checks not applicable, not passed. Packages without this updater need separately recorded installation-owner bootstrap acceptance.

Exercise consecutive updates in the same disposable account with existing conversations through each applicable owner: official installer, uv tool, pipx, ordinary pip venv and source. Check recorded constraints/options before/after, execute the offered command, verify the restarted gateway, append a message and start again. Policy refusal must leave installation unchanged; custom owner-reviewed updates do not prove automatic recovery. Container replacement requires a real engine and retained data volumes, not a mocked marker.

For installer-owned background recovery, verify one exact-target repair, then original-program restoration only before activation and only with unchanged protected data, including restart/health verification without browser or terminal intervention. Data changes, activation, live owners or changed installation ownership must prevent unsafe rollback. Other owners retain their repair route. Never delete jobs/fences or automatically restore old configuration/chat data. Exercise native Windows locks/renames. Loss of both supervisor and worker, permanent storage damage and incompatible data writes are not automatically recoverable; retain these limits in release notes and the operator guide.

Keep private evidence until review; it can contain program generations/backups and is not an upload set. CI retains small reports, including completed cases after a later failure; only all selected journeys passing produces aggregate success. Partial reports or a timeout are not an overall pass. Record actual native OS/CPU coverage separately from installer/startup fixtures: Linux x64, Windows x64 and macOS arm64 do not establish macOS x64 or Linux arm64 coverage. Controlled release transport and fault injection prove neither public downloads nor interactive UI; complete those gates before claiming them.

## Stable and Preview subscriptions

Use [Updating nanobot](./updating.md) for Settings → About and CLI instructions. Release acceptance must preserve opt-in consent: Preview is off even on development builds; switching saves/checks a feed, not installation approval. Require separate exact-version confirmation and a Preview risk warning. Profiles sharing an environment/account share its subscription; other installations/accounts do not. Environment replacement may require reselection; browser storage is not authoritative.

| Current install / requested channel | Required acceptance result |
| --- | --- |
| Stable → Preview, a newer verified preview exists | Offer that exact preview; install only after confirmation. |
| Preview → Preview | Offer only a higher verified version, including a final release. |
| Preview → Stable, stable is newer | Offer the final release; keep Stable selected. |
| Preview → Stable, stable is older | Save Stable and wait for a newer final release; keep running the preview. |
| Preview subscriber installs a final release | Keep Preview selected for the next development cycle. |
| Current preview was withdrawn | Warn even without a safe newer replacement; never silently downgrade. |
| Feed offline, incomplete, missing or incompatible | Return non-success; retain subscription and allow rechecking. |

Stable checking/planning requires complete PyPI wheels/sdist. Preview uses `release-index/catalogue.json` and exact GitHub manifests, never PyPI `--pre` or arbitrary branches. Validate targets against the gateway interpreter/platform, not the browser. Index final releases for Preview subscribers too; advance only after verifying all referenced public assets.

Versions, tags and manifest hashes are immutable. Increment generation; never rewind or clear published pointers, remove withdrawals or reuse bad versions. To stop offering a version, retain its pointer and withdraw it. Serialize writers and validate `ReleaseCatalogue.validate_successor(previous)` against the latest catalogue. Clients reject rewrites relative to their last accepted catalogue; that check is not cryptographic signing.

Acceptance must invalidate reviews on every channel change, including Stable → Preview → Stable; cancel inactive staged work through normal stop checks and retain diagnostics. Active preparation, committed shutdown, admitted installation or failed mutation blocks switching until settled/recovered. Reject stale-tab writes and reread after lost responses, never automatically retry installation. Detailed transaction rules belong in the [update protocol](./update-protocol.md).

Discovery grants no installation authority. Only the official managed venv and supported POSIX uv transactions support the reviewed stop/install/restart flow; pipx, source, container, system-managed, unsupported uv/platform and desktop distributions retain their owner/distributor route. Remote browsers without package-install permission may read status but not change subscription. Older clients must get actionable failures for unrepresentable statuses, never false “up to date.” Verify these boundaries before announcing a public channel.

## Non-publishing preview preflight

**Verify Release Candidate** is manual, read-only preparation: no tags/releases, PyPI or catalogue writes. It builds/checks five platform wheels, sdist and licensed fallback archives. Cross-compilation is neither native execution nor release approval.

Default retention is small identity/manifest/probe reports and installation guide for **three days**, without installable binaries. `retain_installable` preserves those exact checked artifacts plus a self-contained shallow Git repository for **one day** (about 400 MB). Keep this storage exception off for routine preflight or schedules; assess storage and call it out explicitly in workflow-change PRs before merge. Preserve approved handoffs before expiry; rebuilding expired files cannot reuse their verification. The source contains only candidate/source-parent history, not configuration or untracked files. `handoff.json` is written only after copied artifacts verify; interruption is not an accepted handoff.

After assembly, the workflow installs the Linux x64 wheel and binary dependencies into a separate venv without Bun/Node/Git on the install PATH. Isolated Python checks version/commit/import identity, all Vite-manifest assets including lazy chunks through the installed handler, and bundled TUI `--desktop-protocol` with downloads disabled and empty private HOME. With `--gateway`, it starts a private foreground CLI gateway with no provider/MCP configuration, disabled heartbeat and two loopback ports, then checks readiness, protected version identity, HTML and process/listener cleanup. Unix shutdown must be graceful; Windows termination is labelled, not graceful-shutdown evidence. No model task or external channel is exercised.

On another supported platform, check a disposable native installation without changing its package:

```bash
<installed-venv-python> -I scripts/verify_installed_release.py \
  --version <candidate-version> --commit <candidate-commit> \
  --gateway --report <new-report-path>
```

Use the candidate commit, not its parent. The probe rejects checkout imports/unisolated invocation and avoids user configuration/credentials. Omit `--gateway` for assets/TUI only. Reports identify OS/CPU/probes and are success-only, never overwritten; failure cleans up children and prints a bounded redacted log tail. This is package/startup evidence, not interactive UI, managed restart, migration, public-download or five-platform E2E acceptance.

For local preparation, use a full source SHA and new output outside the checkout (illustrative base/sequence):

```bash
python -m scripts.release_candidate prepare \
  --source-commit <full-commit-sha> --base 0.3.6 --sequence 42 \
  --output <new-candidate-directory>
```

Preparation leaves the checkout untouched and deterministically creates a version-only commit for identical inputs. Build Python distributions and all native targets from it, then run from the candidate:

```bash
python -m scripts.release_candidate assemble --source-commit <original-source-sha> \
  --wheel <intermediates>/nanobot_ai-0.3.6.dev42-py3-none-any.whl \
  --sdist <intermediates>/nanobot_ai-0.3.6.dev42.tar.gz \
  --tui-dir tui/dist --output <new-artifact-directory>
```

Assembly refuses existing output and emits the manifest only after complete-set, version/commit, WebUI, RECORD, native/source and permissions checks. It compares sdist sources/resources against tracked candidate files with packaging exclusions, and all wheels' application/WebUI bytes against the sdist. Commit markers and RECORDs alone are insufficient; these comparisons do not prove reproducible frontend/native compilation. Recheck with `python -m scripts.release_candidate verify --source-commit <original-source-sha> --artifacts <artifact-directory>`; it may reuse an identical manifest, never replace different bytes.

Generate the handoff from the same candidate:

```bash
python -m scripts.release_candidate instructions --source-commit <original-source-sha> \
  --artifacts <artifact-directory> --output <new-install-guide-path.md>
```

The generator rechecks artifacts/manifest and writes a non-overwriting guide outside the immutable upload directory. When both installers match the supported implementation, commands fetch the exact candidate's installer with the retained manifest hash for automatic platform selection; older candidates keep manual commands, never mutable `main` or assumed flags. Publication must make pinned installer source reachable.

The guide records version, source/candidate commits, five hash-bound wheel URLs and separate new/existing base-package commands for uv, pipx and pip venv. Commands verify local size/SHA-256 with the standard library before manager invocation; URL hash fragments alone are insufficient for the tested uv commands. Retain wheel paths recorded by managers. Manual commands move to an advanced section when automatic entry is supported; no new manifest schema or installer executable is introduced.

Before offering the guide, publish/verify exact public files and add release changes, native coverage, migration/recovery instructions and stop/backup prerequisites. Review extras and locked/suffixed/external-owner options; independently verify installed version and restarted gateway. Manager fixtures do not prove restart/migration, and the guide is neither publication approval nor channel selection.

The candidate clone borrows source Git objects; preserve its source repository until retained in an approved permanent ref. Partial assembly has no accepted manifest and must not be uploaded. Source-offer commitment, native launch, clean install, upgrade/recovery and publication gates still apply. Missing public assets must be recovered from original verified files, never overwritten by rebuilds.

Retain an exact local handoff outside temporary build storage:

```bash
python -m scripts.release_candidate retain --source-commit <original-source-sha> \
  --artifacts <verified-artifact-directory> --output <new-retained-directory>
```

Only `artifacts/` is the upload set; `source.git/`, `install.md` and `handoff.json` are maintenance evidence, not PyPI packages. Restore with `git clone --no-local <retained>/source.git <new-checkout>`, check HEAD against `handoff.json`, and rerun `release_candidate verify` on retained artifacts before separately approved publication. Keep native reports and release notes alongside them; retention adds no native, migration, interactive UI or public-download evidence.
