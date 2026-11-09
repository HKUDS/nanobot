# Native TUI corresponding source and relinking

The nanobot TUI release archive contains the executable, its complete JavaScript/TypeScript application source, dependency lockfile, build scripts, and third-party notices. The build scripts include the shared target definitions and the resvg binding-loader generator. It is built with Bun 1.3.13 and OpenTUI 0.5.11. See `SOURCE_OFFER.md` for the corresponding-source offer that accompanies the executable. The archive also contains the complete LGPL 2.0 and LGPL 2.1 license texts.

Corresponding upstream source:

- nanobot TUI: the `tui/` and `packages/client-events/` directories in the GitHub release tag that contains this archive
- Bun 1.3.13 (`bf2e2cecf27e800962b1e7f03d66278f9d5d2e79`): <https://github.com/oven-sh/bun/tree/bun-v1.3.13>
- Bun's patched WebKit (`4d5e75ebd84a14edbc7ae264245dcd77fe597c10`): <https://github.com/oven-sh/WebKit/tree/4d5e75ebd84a14edbc7ae264245dcd77fe597c10>
- OpenTUI 0.5.11: <https://www.npmjs.com/package/@opentui/core/v/0.5.11> (source: <https://github.com/anomalyco/opentui/tree/6b9863ea7c5fae22bfebb23c242ddcc4c2b0aa0e>)
- Pele 1.9.0: <https://www.npmjs.com/package/pele/v/1.9.0>
- resvg-js 2.6.2 (MPL-2.0): <https://github.com/yisibl/resvg-js/tree/v2.6.2>. The public `index.js` wrapper and native bindings are unmodified; `tui/scripts/target-bindings.ts` supplies the build-target-specific internal loader and is included in `nanobot-tui-source.tar.gz`. The upstream license text is reproduced in the notices.
- fontkit 2.0.4: <https://www.npmjs.com/package/fontkit/v/2.0.4>; fontkit, dfa 1.2.0, and brotli 1.3.3 declare MIT in their upstream README files, which are reproduced in the notices because these npm releases have no standalone license file. Exact dependency versions and tarball integrity are pinned in `bun.lock`.

To rebuild against a modified JavaScriptCore/WebKit, first build Bun 1.3.13 from its complete source checkout together with the WebKit revision above by following Bun's pinned license and build instructions. Then unpack `nanobot-tui-source.tar.gz` from the release archive and run the resulting Bun executable:

```bash
cd nanobot-tui-source/tui
/path/to/modified/bun install --frozen-lockfile
/path/to/modified/bun scripts/prepare-target.ts <target>
/path/to/modified/bun run build -- <target>
```

Supported targets are `darwin-arm64`, `darwin-x64`, `linux-arm64`, `linux-x64`, and `win32-x64`. The resulting executable is written to `dist/`.

Use the same `<target>` for preparation and compilation. `scripts/targets.ts` defines the native package set and Bun compile target; `scripts/target-bindings.ts` generates the target's internal resvg loader without modifying installed dependency source. Linux targets retain GNU and musl bindings, and x64 targets use Bun's baseline CPU variant.

The included build script bundles minified JavaScript and the standalone Bun runtime without the additional precompiled bytecode cache; this is a build policy, not a runtime option.

Questions about source availability can be reported at <https://github.com/HKUDS/nanobot/issues>.
