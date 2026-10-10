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

#### Computer Use payloads for macOS

Before packaging the two macOS wheels, build `native/computer-use` from this exact
release checkout on the matching Mac architectures. Use the pinned Cua source
revision and committed Cargo.lock, following its [build guide](../native/computer-use/README.md).
Keep `native-package.json` and `native-package.tar.gz` under
`<verified-computer-use>/darwin-arm64/` and `darwin-x64/`. These are inert wheel
payloads, not a second user-visible installer. Linux/Windows use the pinned
official driver and do not include this payload.

Run `verify_package.py --runtime` on each Mac: default installation without
developer staging, signature verification, status/tool discovery without capture,
observation-mode input refusal, stopped-sharing refusal, uninstall and reinstall.
Separately test a downloaded wheel in a fresh account with no previous TCC grants:
Apps must install only **nanobot Computer Use**, request the two grants sequentially,
show the real system sharing indicator and branded cursor during a bounded task,
and respect Stop Sharing, cancellation and uninstall. Record each architecture's
native evidence; fixture tests and cross-compilation are not a substitute.

Review the target-specific notices, pinned Cua MIT and derived-code credits,
Inter's OFL, and bundled MPL sources/license. `NANOBOT-SOURCES.tar` must match this
checkout. The packager rejects missing, stale or mismatched payloads. No user
configuration, temporary sockets or build caches belong in the archive.

The current builder ad-hoc signs the app. That is **not** Developer ID signing or
Apple notarization and does not establish a clean Gatekeeper download experience.
Before public release, record the maintainer's distribution/signing decision and
prove the downloaded-install flow without disabling system protections. If that
flow needs Developer ID/notarization, complete it and regenerate the hashes before
publishing; do not claim that ad-hoc signatures satisfy it. No macOS GitHub Actions
runner is added by this feature; use local/release infrastructure under the existing
CI policy. Do not publish a macOS wheel with a missing native package or silently
fall back to a differently named permission owner.

From the exact release checkout, after `uv build` and the native archive checks:

```bash
uv run python -m scripts.build_tui_wheels \
  --wheel <intermediates>/nanobot_ai-X.Y.Z-py3-none-any.whl \
  --tui-dir <verified-tui-archives> \
  --computer-use-dir <verified-computer-use> \
  --out-dir <final-wheels>
```

The script verifies the Python version and RECORD, native checksums, architecture, notices and embedded source against the checkout, then writes five wheels with complete TUI bundles and regenerated RECORDs. It refuses to overwrite an existing candidate. `--target <target>` builds one platform for a targeted check. Minimum tags are macOS 13, manylinux glibc 2.17 and Windows x64; x64 builds use Bun's baseline (SSE4.2) runtime instead of requiring AVX2. Recheck both Bun and OpenTUI when upgrading either dependency. No musl or Windows ARM64 wheel is provided. Native execution checks must still validate the actual binaries; tags alone do not prove compatibility. Test pip selection for all five supported platforms.

Computer Use is optional and requires macOS 14.2+, independently of the macOS 13
minimum for Python/TUI. The macOS wheel contains its app payload and notices;
installing the wheel does not launch the app or enable desktop access. Existing
official driver installations retain their identity; switching requires explicit
disable/uninstall/reinstall. Source-only installations do not contain native
binaries and need a matching platform wheel or a build from the matching checkout.

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

Do not publish to PyPI while a required TUI or Computer Use artifact or verification is missing. Keep the documentation's public `latest` on the previous stable version until the new version is usable. If a published package needs a correction, prepare a new version; do not silently replace the code behind an existing release tag. Stop all old processes and follow the documented session rollback procedure before downgrading a migrated installation.
