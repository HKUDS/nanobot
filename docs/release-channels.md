# Stable and preview channels

Status: proposal for review, not an available preview service. This document defines
the release pipeline and acceptance work that must precede a channel selector.
It does not enable scheduled builds, publish packages, or change existing installations.

The update executor is tracked in [PR #5817](https://github.com/HKUDS/nanobot/pull/5817).
Keep publication policy separate from installation execution. A source checkout update
is not a published preview release.

## Product contract

| Channel | Intended user | Cadence | Default behavior |
| --- | --- | --- | --- |
| Stable | Normal installations and production gateways | Monthly feature releases; small patch releases when fixes are ready | New installations remain on stable |
| Preview | Users who explicitly want recent, tested changes | At most one release per UTC day when the tested source changes; manual candidates for urgent validation | Explicit opt-in; no forced migration from stable |
| Source | Contributors using a checkout | The selected branch and upstream | Keep the branch; do not label arbitrary source as preview |

Use one development branch, `main`. Do not restore the removed `nightly` branch or
require contributors to maintain two branches. [PR #4245](https://github.com/HKUDS/nanobot/pull/4245)
removed that workflow; release channels select artifacts, not contribution branches.

A check for updates is read-only. Installing, changing channel, and restarting require
an explicit action. A compatible version difference must not interrupt a conversation.
There is no unattended installation in this proposal.

## Versions and release identity

Use the existing `nanobot-ai` distribution for both channels. Stable versions remain
`X.Y.Z`. Preview versions use `<next-stable>.dev<N>`, with a strictly increasing,
unique integer allocated by the release pipeline. For example,
`0.3.6.dev12345 < 0.3.6`; the example is not a published release.

- Allocate the next stable version explicitly. Do not infer a release target from the
  current date or silently move a preview to a different release line.
- Bind each version to a full source commit, build inputs, and artifact hashes.
- A workflow retry reuses its recorded candidate, not the new `main` tip. If the
  candidate or published bytes change, allocate a new version.
- Use an immutable Git tag matching the package version. Mark preview GitHub Releases
  as prereleases and never select them as GitHub's latest stable release.
- Never force-move a published tag or overwrite an uploaded asset. The current
  `tui-release.yml` overwrite behavior must change before this pipeline is enabled.
- Do not derive preview availability from PyPI's single `info.version` field.
  Select eligible versions from release metadata, excluding yanked, incomplete, and
  incompatible candidates. Stable checks exclude all prereleases.
- Pin the selected nanobot version exactly. Do not use a global pip `--pre` flag that
  also permits prereleases for unrelated dependencies.

These rules use [Python version ordering](https://packaging.python.org/en/latest/specifications/version-specifiers/).
The selected version and channel belong to the gateway installation, not to a browser,
chat, model, or remote host selected elsewhere.

## Build and publication pipeline

The stable [release checklist](./releasing.md) remains authoritative. Previews need
the same complete package, source, license, and platform checks, not a reduced package.

1. Select a green, exact `main` commit. Skip a scheduled run when that source was
   already published or a previous candidate is still incomplete.
2. Allocate and record the candidate version. Prepare a clean candidate tree with
   matching Python metadata and source fallback version. Do not edit a maintainer's
   active checkout or combine independently resolved revisions.
3. Run candidate checks and build the WebUI, source distribution, five native TUI
   archives, and five platform wheels from that tree. Reuse the existing build and
   packaging scripts. Do not publish the intermediate universal wheel.
4. Verify versions, native architectures, archive manifests, wheel RECORDs, checksums,
   notices, corresponding source, and relinking material. Preserve one provenance
   manifest containing all artifact hashes and the candidate commit.
5. Test installation and upgrade in disposable environments. Verify native TUI launch
   without a network download and WebUI startup from installed assets. Do not confuse
   cross-compilation with native execution.
6. Pass a protected publication gate. The maintainer must approve the applicable
   source-offer commitment, source retention, candidate checks, and publishing identity.
7. Publish the immutable tag and matching GitHub prerelease with verified TUI fallback
   archives. Verify public downloads before uploading the same five wheels and one
   sdist to PyPI.
8. Test a clean public installation. Only then mark the candidate available in the
   channel feed. A partial upload is not an available update.

A scheduled build must not bypass an approval required for publication. Start with a
manually triggered candidate workflow and no publish credentials in build jobs. Enable
the daily trigger only after the full manual path has passed.

Before automation is implemented, decide how preview candidate commits are retained
without creating daily version-bump churn on `main`. A protected release-candidate
ref with only the reviewed version changes is proposed. Its source tree must match
the tested and tagged tree. This needs an explicit preview exception to the current
merge-before-tag checklist; the stable process must not change incidentally.

Prefer [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) with a
repository/workflow/environment-scoped identity. Build jobs have read-only access.
Publishing jobs consume verified artifacts from the selected run, not arbitrary URLs,
untrusted PR artifacts, or a mutable branch. Configure the PyPI trust and protected
environment with maintainer approval; do not place a shared token in source.

Use standard Ubuntu/Windows runners and short retention for disposable CI artifacts.
Published binaries and corresponding source follow their release obligations, not the
CI retention setting. Measure the five-wheel and archive storage cost before setting
an ongoing cadence. Do not assume daily native bundles fit the available PyPI quota.

## Installation methods

The gateway must first identify the environment that owns its running interpreter.
Do not select an installer from the user's PATH alone.

| Installation | Update owner | Required channel behavior |
| --- | --- | --- |
| Recommended shell/PowerShell installer | Its recorded backend and environment | Preserve backend, interpreter, extras, and instance configuration |
| uv tool | uv tool receipt | Preserve constraints/settings; changing a pin is an explicit reinstall plan |
| pipx | pipx environment metadata | Preserve suffix, injected packages, interpreter, and install arguments |
| pip virtual environment | That environment's Python | Install the exact target; verify dependencies and actual restart import path |
| Editable source | The current checkout and branch | Fast-forward only when clean; not a preview channel |
| Container / Compose | Deployment configuration | Show the verified image/tag or source rebuild instructions; do not run pip in the container |
| Service-managed gateway | Its package/deployment owner and supervisor | Update the owner, then use the correct supervisor restart path |
| Desktop application | Desktop distributor | Do not replace embedded Python through the gateway updater |

The current draft executor uses manual manager-specific guidance for uv tool and pipx;
inline adapters are not implemented. Channel switching for those managers must be tested
before advertising it. In particular, [uv tool upgrades retain their original constraints
and settings](https://docs.astral.sh/uv/concepts/tools/#upgrading-tools), and
[pipx owns its environment metadata](https://pipx.pypa.io/stable/reference/metadata.html).
Do not use a direct pip update as an undocumented substitute.

No official container image channel is assumed: the current Compose path builds source.
Supporting versioned images requires a separate publication and digest contract.

## In-app experience

Keep one update section in Settings → About, using the existing settings components.
The gateway owns availability, installation identity, update progress, and policy.

The section should answer, in this order:

1. Which gateway is this, and which version/channel is actually running?
2. Is a compatible update available for its installation method?
3. What changes, and what exact version would be installed?
4. Does the action require a channel switch, backup, task stop, or external installer?

Use an explicit state flow:

`Check → Review target and notes → Confirm → Prepare → Install → Restart required → Verify running gateway`

The network-error state must offer retry, not say “up to date.” Show one primary action
for the current state. Preserve progress across refresh and reconnection. If the gateway
process disappears, distinguish reconnecting from installation success.

The confirmation binds an exact candidate and installation identity. Reject a stale plan
when either changes. Serialize updates across processes sharing that Python environment.
Coordinate active tasks and supervisor restart; a browser checkbox alone is not an
enforced maintenance window.

After restart, verify the gateway's running package path, version and, where applicable,
commit. A successful pip command or a version shown by another PATH executable is not
proof. Keep named optional capabilities so older compatible hosts retain all unrelated
features without receiving unsupported update requests.

## Return to stable and failure recovery

Do not promise that selecting stable is always a harmless upgrade. A preview can be
newer than the latest stable version or can have migrated data.

- Show whether the proposed change is an upgrade, downgrade, or source/deployment change.
- Require explicit confirmation for a downgrade. Keep a usable backup of configuration,
  sessions, transcripts, and other independently durable state before migration.
- Stop all old processes before restoring compatible data. A new runtime must not keep
  writing while an older runtime reads the restored state.
- Test the documented recovery from representative old installations through actual
  list/open/append operations, not only successful startup.
- On installation or restart failure, retain the target, last completed stage, and
  recovery instruction. Do not report “rolled back” unless rollback was verified.
- Recommend separate preview data for early adopters until downgrade compatibility is
  proven. Do not delete or silently rename the user's stable data.

The current OpenAI selector migration has a two-release support window. Before previews
are enabled, amend the release policy to say whether that means stable releases or every
published candidate. Recommended: two consecutive stable releases, with preview support
covering that window. This proposal does not silently change the existing policy.

## Rollout gates

- [ ] Agree on version allocation, candidate-ref policy, cadence and storage budget.
- [ ] Implement manual candidate preparation and complete, non-publishing artifact CI.
- [ ] Verify source-offer commitments and retained corresponding-source materials.
- [ ] Configure protected publication and PyPI trust, then publish one approved preview.
- [ ] Verify fresh install and upgrade for pip/uv/pipx/installer on macOS, Windows and Linux.
- [ ] Verify failure recovery, no-op, downgrade rejection, task coordination and supervisor restart.
- [ ] Add gateway channel selection, exact-target plans and installer-specific adapters to the executor.
- [ ] Exercise desktop/mobile browsers, remote hosts, missing capabilities and reconnect.
- [ ] Update stable/preview/source documentation and release notes without advertising an unavailable build.
- [ ] Enable at-most-daily publication after measuring the first candidate's cost and reliability.

The repository docs belong with these changes. The external documentation site needs
a separate authorized update when a preview is actually installable. Its stable
`latest` routes must stay on the published stable version.
