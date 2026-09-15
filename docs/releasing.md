# Release checklist

Use this checklist with the [Release Packaging Contract](../CONTRIBUTING.md#release-packaging-contract).
Preparing a release does not publish it. Pushing a Git tag, publishing a GitHub Release,
uploading to PyPI, and deploying the documentation are separate operations.

## Prepare a candidate

1. Choose the previous release and the exact candidate commit. Work in a clean worktree;
   do not include local configuration, session data, credentials, or unrelated changes.
2. Update `project.version` in `pyproject.toml` and the final source-only fallback in
   `nanobot/__init__.py`. Private WebUI/TUI package versions are not the Python release version.
3. Review the changes since the previous tag. Write highlights, upgrade and rollback guidance,
   contributor acknowledgements, and the full changelog. Verify counts against the final
   range; commit counts are not merged-PR counts. Coordinate security disclosures separately.
4. Run the Python, WebUI, and TUI checks from CI. Confirm the final commit's CI status, not
   just an earlier PR head. Review installation, configuration, session, and API changes.
5. Build in a clean output directory with `uv build --out-dir <artifact-directory>`.
   Do not set `NANOBOT_SKIP_WEBUI_BUILD`. The build hook bundles the WebUI in the sdist and
   wheel; the wheel is built from the sdist.
6. Check the two distributions with `twine check`, inspect their contents, and record SHA-256
   hashes. Test installation in an isolated environment outside the source checkout, then
   test upgrading from the previous stable version using disposable configuration and sessions.
   Do not use a maintainer's live workspace for migration tests.
7. Prepare the matching documentation PR in `Re-bin/nanobot-web`, following its
   `MAINTAINING.md`. Review English and all nine translations, preserve Nightly and previous
   releases, update the latest-version redirects, and run the complete site quality gate.
   Candidate docs may be prepared from a commit, but must be checked against the final tag.

Keep an artifact manifest with the source commit, version, filenames, hashes, checks performed,
and any remaining release gates. Rebuild and recheck if the packaged source changes.

## Publish, with maintainer approval

1. Merge the release-preparation PR and confirm the final commit. Create and push exactly
   `vX.Y.Z`; do not move or reuse a published version tag.
2. Create the matching GitHub Release. A draft may be used while assembling its attachments.
   Pushing the tag alone does not run `Publish Terminal UI` or upload anything to PyPI.
3. Review the pinned Bun/OpenTUI licenses, corresponding-source materials, source-offer
   commitment, and relinking instructions for that exact tag. Only then confirm the
   compliance input and manually run **Publish Terminal UI** with `tag=vX.Y.Z`.
4. Wait for all five targets: macOS arm64/x64, Linux arm64/x64, and Windows x64. Each needs
   its release archive and `.sha256` file. Check the archive contents required by the
   packaging contract. A successful build is not a substitute for compliance review.
5. Make the GitHub Release and all TUI attachments publicly available. Verify their public
   downloads before publishing Python, since installed clients fetch version-matched assets.
6. Upload only the checked `nanobot_ai-X.Y.Z.tar.gz` and `nanobot_ai-X.Y.Z-py3-none-any.whl`
   to PyPI. Do not upload stale files from a shared `dist/` directory. This repository has no
   automatic PyPI publication workflow.
7. Verify installation from PyPI, bundled WebUI startup, and the matching TUI download in
   clean environments. Merge the prepared wiki PR only when the stable package is available:
   merging its `main` deploys the site automatically. Confirm all localized `/docs/latest/`
   routes select the new version and old version links still work.
8. Publish the release announcement and add the dated entry to
   [Release Archive](./release-archive.md). Complete any coordinated advisory publication and
   reporter notification. Record links and completion status in the release tracking issue.

## If a gate fails

Do not publish to PyPI while a required TUI artifact or verification is missing. Keep the
documentation's public `latest` on the previous stable version until the new version is usable.
If a published package needs a correction, prepare a new version; do not silently replace
the code behind an existing release tag. Stop all old processes and follow the documented
session rollback procedure before downgrading a migrated installation.
