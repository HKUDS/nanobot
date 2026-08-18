# Native TUI corresponding source and relinking

The nanobot TUI release archive contains the executable, its complete JavaScript/TypeScript
application source, dependency lockfile, build scripts, and third-party notices. It is built with
Bun 1.3.13 and OpenTUI 0.5.3. See `SOURCE_OFFER.md` for the corresponding-source
offer that accompanies the executable. The archive also contains the complete LGPL 2.0 and
LGPL 2.1 license texts.

Corresponding upstream source:

- nanobot TUI: the `tui/` directory in the GitHub release tag that contains this archive
- Bun 1.3.13 (`bf2e2cecf27e800962b1e7f03d66278f9d5d2e79`):
  <https://github.com/oven-sh/bun/tree/bun-v1.3.13>
- Bun's patched WebKit (`4d5e75ebd84a14edbc7ae264245dcd77fe597c10`):
  <https://github.com/oven-sh/WebKit/tree/4d5e75ebd84a14edbc7ae264245dcd77fe597c10>
- OpenTUI 0.5.3: <https://www.npmjs.com/package/@opentui/core/v/0.5.3>

To rebuild against a modified JavaScriptCore/WebKit, first build Bun 1.3.13 from its complete
source checkout together with the WebKit revision above by following Bun's pinned license and
build instructions. Then unpack
`nanobot-tui-source.tar.gz` from the release archive and run the resulting Bun executable:

```bash
cd nanobot-tui-source
/path/to/modified/bun install --frozen-lockfile
/path/to/modified/bun run build -- <target>
```

Supported targets are `darwin-arm64`, `darwin-x64`, `linux-arm64`, `linux-x64`, and `win32-x64`.
The resulting executable is written to `dist/`.

Questions about source availability can be reported at
<https://github.com/HKUDS/nanobot/issues>.
