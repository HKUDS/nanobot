// SPDX-License-Identifier: MPL-2.0
// Target-specific replacement for resvg-js 2.6.2's generated binding loader.
import { createRequire } from "node:module"
import { dirname, join, resolve } from "node:path"
import type { BunPlugin } from "bun"
import type { TargetPlan } from "./targets"

// This adapter replaces only the generated loader, not resvg's public options wrapper.
// Review the loader contract and these identities together when updating resvg.
const resvgVersion = "2.6.2"
const resvgSources = {
  "index.js": "b670803d88b380b0610edf743d8b74dcc132d9e2aa6aaa04cfaa06b2fcad397d",
  "js-binding.js": "d5fbe3b7450d1e393ea9856e86e16465d25be8743cae7db03e2f3249aed61e56",
}

export async function targetBindings(plan: TargetPlan, root: string): Promise<BunPlugin> {
  const require = createRequire(join(root, "package.json"))
  const entry = require.resolve("@resvg/resvg-js")
  const packageRoot = dirname(entry)
  const manifest = await Bun.file(join(packageRoot, "package.json")).json()
  if (manifest.version !== resvgVersion) throw new Error(`review resvg target bindings for version ${manifest.version}`)
  for (const [name, expected] of Object.entries(resvgSources)) {
    const digest = new Bun.CryptoHasher("sha256").update(await Bun.file(join(packageRoot, name)).arrayBuffer()).digest("hex")
    if (digest !== expected) throw new Error(`review resvg target bindings: ${name} changed`)
  }

  // Absolute resolutions keep the virtual module independent of the build host's cwd.
  const binding = (name: string) => `require(${JSON.stringify(require.resolve(name))})`
  const load = plan.platform === "linux"
    ? `
function isMusl() {
  if (!process.report || typeof process.report.getReport !== "function") {
    try {
      const lddPath = require("node:child_process").execSync("which ldd").toString().trim();
      return require("node:fs").readFileSync(lddPath, "utf8").includes("musl");
    } catch { return true; }
  }
  return !process.report.getReport().header.glibcVersionRuntime;
}
const nativeBinding = isMusl() ? ${binding(plan.bindings.musl.resvg)} : ${binding(plan.bindings.gnu.resvg)};
`
    : `const nativeBinding = ${binding(plan.bindings.native.resvg)};`
  const contents = `${load}
const { BBox, Resvg, RenderedImage, renderAsync } = nativeBinding;
module.exports = { BBox, Resvg, RenderedImage, renderAsync };
`

  return {
    name: "nanobot-resvg-target",
    setup(builder) {
      builder.onResolve({ filter: /^\.\/js-binding\.js$/ }, (args) => {
        if (resolve(args.importer) === resolve(entry)) return { path: "binding", namespace: "nanobot-resvg" }
        return undefined
      })
      builder.onLoad({ filter: /^binding$/, namespace: "nanobot-resvg" }, () => ({ contents, loader: "js" }))
    },
  }
}
