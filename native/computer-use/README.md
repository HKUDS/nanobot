# nanobot Computer Use native host

Local macOS candidate, not an official Cua release. It embeds Cua's MIT SDK at
`d27f6a89d8aeef0f56363ee9bb60bbc565912b1e` (the tested PR #3019 snapshot), including
its original multi-display cursor implementation and contributor credit.
Source: https://github.com/trycua/cua/pull/3019 . This is not Cua 0.33.4.

The host contains no model, agent loop or network server. A private per-gateway
Unix socket accepts the finite nanobot desktop surface. Only an observed window
can receive input. The SDK owns input, snapshots and cursor animations. A real
ScreenCaptureKit window stream owns macOS sharing indication. It records no
audio, saves no frames and never falls back to full-display capture.

System Stop Sharing revokes the SDK session and latches a local pause. Tool
retries and MCP reconnections cannot clear it; explicit Apps reconnect is required.
Disconnecting the MCP transport closes its stream/session. Idle sharing closes
after 60 seconds. Settings checks never create a stream or request permission.

Build using a checkout containing the exact upstream commit:

```
python3 native/computer-use/build.py --source /path/to/cua --output /new/output/path
```

The output is an ad-hoc-signed local app, with nanobot's icon and the original
Cua MIT notice plus dependency notices. This signature is not Developer ID or
notarization. macOS grants must be given to this exact app; rebuilding can require
renewed grants. A public signed binary release needs separate signing/release work.
No upstream signature, logo identity or official installation is replaced.

Verify the produced package without capturing content or requesting permissions:

```
python native/computer-use/verify_package.py /output/native-package.json --runtime
```

This exercises install, native status/tool discovery, observation-mode input
denial, stop/restart refusal, uninstall and reinstall in a disposable directory.
Omit `--runtime` for a completely offline installation-only check.

With Computer Use disabled and the previous managed driver (official or native)
uninstalled, stage the
verified build using the gateway's Python environment:

```
python -c 'from pathlib import Path; from nanobot.apps.computer_use_native import register_package; register_package(Path("/gateway/config.json"), Path("/output/native-package.json"))'
```

Then install from Apps. Rebuilding does not automatically replace an installed
package. Staging refuses to hide an existing managed installation. Uninstall
deletes only the managed installed directory; the staged archive remains for
reinstall. The native app's uninstall confirmation optionally resets Accessibility
and Screen Recording using Apple's `tccutil`, scoped to `io.nanobot.computer-use`.
This option is off by default and affects every instance of that identity on the
same Mac. It never resets official CuaDriver or another app. A failed reset keeps
the disabled package available for retry; it can have partially revoked grants.
Without this option, uninstall preserves macOS grants. Reinstall never enables
the MCP connection automatically.

The dependency graph is not exclusively MIT: UniFFI uses MPL-2.0. Its unchanged
source is bundled in `Contents/Resources/MPL-SOURCES.tar.gz`, with its original
license. Third-party notices contain versioned source links; nanobot/Cua source
remains under MIT. Local validation does not constitute public release approval.

New nanobot source is MIT under the repository LICENSE. The branded cursor is
adapted from Cua's MIT authoring helpers; its manifest retains attribution.
