# CI execution boundaries

Code validation and release acceptance have different owners. `Test Suite` validates PRs and the merged `main` tree. `Verify Release Candidate` builds an explicit candidate and validates its exact installable bytes. Neither workflow publishes releases, signs manifests or advances `release-index`; that branch is a release catalogue, not a product source branch.

## Code validation

`scripts/ci_scope.py` owns the ordered path rules and explains each decision in the run summary. PR selection uses the merge-base diff; pushes use the complete before/after range, including all commits in the push. Renames consider both old and new paths. Missing revisions, failed or empty diffs, unknown paths and manual dispatch select the full validation set. Ordinary documentation changes still produce the stable `CI required` result without scheduling product jobs.

Python retains its Linux minimum/latest and Windows compatibility matrix. WebUI changes retain lint, types, unit coverage, build, browser regression and Docker checks. TUI functionality retains both platforms' checks, tests, terminal smoke, build and archive verification. Shared backend client contracts select the consuming clients as well. Docker continues checking installed assets, startup, dependencies and container privilege boundaries; frontend changes are not assumed irrelevant to the image.

Native packaging, installation and update lifecycle changes additionally select Linux and Windows native acceptance on PRs. Windows isolated update jobs and installer checks use the same high-risk selection. The installer matrix has its own bounded job, separate from process-identity checks; an 18-minute installer run must not consume the process job's timeout or hide its result. Pushes to `main` run the selected code checks but do not repeat those specialized installer/update journeys or full native acceptance. A manual `Test Suite` dispatch requests all checks. Scope changes must keep new shared contracts and lifecycle dependencies classified; directory names alone do not establish the dependency graph.

`CI required` checks the selected job results, including matrix and reusable-workflow results. Failure, cancellation, an unexpected skip or a missing selector output fails the gate. Only an intentional unselected skip is accepted. Administrators should require this stable check in branch protection/rulesets; defining the job does not enable repository protection or remove any existing required check.

## Candidate acceptance

The candidate producer builds five platform bundles and records the candidate commit and manifest SHA-256. It transfers only the Linux x64 and Windows x64 wheels and the manifest to parallel native consumers. Consumers download by immutable producer artifact IDs, including when only failed jobs are retried, and verify the build-output manifest hash, candidate commit, wheel size/hash and embedded commit before installing or executing the wheel. They never rebuild candidate packages. The same reusable native acceptance workflow also builds private test packages for high-risk PRs.

Each native consumer runs the clean public installer, installed startup/assets probes, and all nine packaged upgrade/recovery scenarios, including subsequent successful updates after restoration. Windows acceptance retains the default short-path policy. Scenarios remain serial within their private environment: sharing that installation across parallel scenarios would invalidate the test. These controlled version/fault fixtures do not replace real supported historical baselines, public-download acceptance, other native platforms, or interactive UI acceptance; see [the release checklist](releasing.md).

`Candidate required` requires both the producer and the complete native matrix. Only after success may an explicitly requested prepared source/installation handoff be promoted to `installable-candidate`. Temporary same-run wheel transfers expire after one day, even when no installable handoff was requested. Reports are retained for three days; an explicitly requested installable handoff expires after one day. Preserve accepted bytes and evidence before expiry. The final gate is not publication approval: the existing separate approval, public artifact verification and serialized catalogue advancement remain mandatory.

## Timing and evidence

Packaged acceptance writes `packaged-update-timings.json` incrementally, including failed phases and completed scenarios. It measures environment setup, initial dependencies, fixture generation, baseline installation, each preparation/worker/verification journey, cleanup and scenario totals. Scenario totals overlap their phases and must not be added to them. Completed checkpoints are diagnostic evidence, not an overall pass.

Upload only the explicit structured reports. Private acceptance logs, configuration, sessions, backups and live test environments can contain credentials and are not upload sets. Do not remove hash checks or durable production writes merely to reduce CI time. Compare wall time and raw runner-minutes separately, with the same scenario coverage and exact source/produced package identity; moving work out of daily CI does not prove that the specialized acceptance itself became faster.
