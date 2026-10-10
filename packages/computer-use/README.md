# nanobot Computer Use native host

This package owns the native executable, SDK patches, build tools and license
materials. Python installation and runtime integration stay in `nanobot/apps/`;
Apps uses the shared WebUI. Generated SDK sources (`.cua-source/`), Cargo output
(`target/`) and release output (`dist/`) are local build inputs, not tracked source
or contents of the first-party source archive. Moving this package does not change
installed paths, app identity or macOS permissions.

This is nanobot's macOS host, **not an official Cua release**. It embeds Cua's
MIT SDK at `d27f6a89d8aeef0f56363ee9bb60bbc565912b1e` (SDK 0.22.1, the tested
[PR #3019 snapshot](https://github.com/trycua/cua/pull/3019)), including its
multi-display cursor implementation. It is not Cua Driver 0.33.4.
The MIT patch in `patches/keep-overlay-host-alive.patch` keeps administration
available when macOS reports no active display. Display reconnection rebuilds
cursor surfaces; the patch neither captures content nor grants permissions.

## Distribution and identity

New installations on macOS 14.2+ use **nanobot Computer Use**, bundle identifier
`io.nanobot.computer-use`, with nanobot's orange/pink icon. The macOS platform
wheel carries the verified payload in `nanobot/apps/computer_use_bundle/`.
Apps installs it into the gateway's data directory, without launching it or
granting desktop access. The model and WebUI cannot choose package paths or URLs.
There is no silent fallback to another permission identity if the payload is missing.

An existing official CuaDriver installation keeps its identity, signature and
permissions. Existing explicitly staged native builds also remain usable. To
switch identities, disable and uninstall the previous package first; grants do
not migrate. Linux and Windows retain the pinned official 0.33.4 installer.

The current builder uses **ad-hoc signing, not Developer ID or Apple notarization**.
It does not borrow an upstream signature or bypass Gatekeeper. Rebuilds may need
renewed macOS grants. Public distribution requires the release preflight in
`docs/releasing.md`, including a clean downloaded-install check and a maintainer
decision on signing; passing unit tests is not release approval.

## Build and verify

On a Mac matching the desired architecture, use a Git checkout containing the
exact Cua revision and the checked-in downstream Cargo.lock:

```bash
python3 packages/computer-use/build.py --source /path/to/cua --output /new/payloads/darwin-arm64
PYTHONPATH=. python packages/computer-use/verify_package.py /new/payloads/darwin-arm64/native-package.json --runtime
```

Use `darwin-x64` on an Intel Mac. The output directory must not exist. Rust,
Cargo (with matching rust-src and rust-docs) and Xcode command-line tools are build-time dependencies, not end-user
requirements. The executable is built with the release profile and a macOS 14.2
deployment target. The builder never launches the app or requests permissions.

The two distribution inputs are `native-package.json` and `native-package.tar.gz`.
The manifest binds architecture, version, source revision, release profile,
application-source checksum and archive checksum. The wheel packager validates
these plus app identity, Mach-O architecture, source and attribution completeness.
Missing material stops packaging. It does not publish the package.

`verify_package.py` exercises the **default bundled-payload path**, with no
per-gateway registration: install, status/tool discovery, observation-mode input
denial, stop/restart refusal, uninstall and reinstall in a disposable directory.
It never captures content or requests permissions. Omit `--runtime` for an
installation-only check. The source verifier rejects stale payloads after a
native-source or compliance-input change.

For an editable source checkout, build directly to the ignored directory
`nanobot/apps/computer_use_bundle` to use the same default Apps flow. A source
distribution does not contain native binaries; use the matching macOS wheel or
build from the matching repository revision. Explicit `register_package` remains
available for isolated developer builds, but is not required by ordinary installs.

## Runtime and lifecycle

The host contains no model, agent loop or network server. A private per-gateway
Unix socket accepts the finite nanobot desktop surface. Only an observed window
can receive input. Cua owns input, snapshots and cursor animations. A real
ScreenCaptureKit window stream supplies macOS's sharing indicator. That stream
records no audio, saves no frames and never falls back to full-display capture.
Agent screenshots use the gateway's normal media path and may reach its selected
model. Window selection is not an app allowlist.

System **Stop Sharing** revokes the SDK session and latches a local pause.
Tool retries and MCP reconnections cannot clear it; explicit Apps reconnect is
required. Task completion/cancellation closes its stream/session. Idle sharing
closes after 60 seconds. Settings checks never create a stream or request grants.

Disable stops this gateway's managed runtime. Uninstall removes only its verified
installation, not chats or other apps. The distribution payload remains available
for reinstall. Native uninstall can optionally reset Accessibility and Screen
Recording through Apple's `tccutil`, scoped to `io.nanobot.computer-use`. This is
off by default and affects every instance of that identity on the same Mac.
It never resets official CuaDriver or another app. A failed reset keeps the
disabled package for retry; some grants may already have been revoked. Without
this option, macOS grants remain. Reinstall never enables MCP automatically.

## Licenses and corresponding source

Nanobot and Cua source retain their MIT licenses. This does **not** make every
dependency MIT. The package contains full target-specific dependency notices,
the retained MIT credits for code derived from yabai and other upstream projects,
and the Inter font's SIL Open Font License. Exact-revision license supplements
and Rust standard-library notices (including the toolchain version) also travel
with the app in `RUST-NOTICES.txt` and `RUST-COPYRIGHT-library.html`. License supplements
for crates that omit their license file are recorded in `licenses/sources.json`.
The original objc2 notices, including their Apple SDK provenance caveat, are
preserved; nanobot does not provide a broader legal assurance than upstream.

UniFFI dependencies retain MPL-2.0. Their unchanged complete crate source and
full license are bundled in `Contents/Resources/MPL-SOURCES.tar.gz`, without
additional restrictions. `NANOBOT-SOURCES.tar` contains this host's code, pinned
Cargo.lock, build scripts, license inputs and artwork. Versioned crate links and
the pinned Cua revision accompany them. Keep all of these materials with any
redistributed executable; nanobot's MIT license does not replace them or grant
rights to Cua's marks. The branded cursor adapts Cua's MIT authoring helpers and
retains attribution. The release verifier is an engineering check, not legal advice.
