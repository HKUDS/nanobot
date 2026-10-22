import { join } from "node:path"

const packagesByTarget: Record<string, string[]> = {
  "darwin-arm64": ["@opentui/core-darwin-arm64", "@resvg/resvg-js-darwin-arm64"],
  "darwin-x64": ["@opentui/core-darwin-x64", "@resvg/resvg-js-darwin-x64"],
  "linux-arm64": ["@opentui/core-linux-arm64", "@opentui/core-linux-arm64-musl", "@resvg/resvg-js-linux-arm64-gnu", "@resvg/resvg-js-linux-arm64-musl"],
  "linux-x64": ["@opentui/core-linux-x64", "@opentui/core-linux-x64-musl", "@resvg/resvg-js-linux-x64-gnu", "@resvg/resvg-js-linux-x64-musl"],
  "win32-x64": ["@opentui/core-win32-x64", "@resvg/resvg-js-win32-x64-msvc"],
}

const target = process.argv[2]
if (!target) throw new Error("target is required")
const packages = packagesByTarget[target]
if (!packages) throw new Error(`unsupported target: ${target}`)

const root = join(import.meta.dir, "..")
const manifest = await Bun.file(join(root, "package.json")).json()
const versions: Record<string, string> = {}
for (const name of ["@opentui/core", "@resvg/resvg-js"]) {
  const version = manifest.dependencies?.[name]
  if (typeof version !== "string" || !/^\d+\.\d+\.\d+$/.test(version)) throw new Error(`${name} must use an exact version`)
  versions[name] = version
}

const npm = process.platform === "win32" ? "npm.cmd" : "npm"
const result = Bun.spawnSync(
  [
    npm,
    "install",
    "--no-save",
    "--ignore-scripts",
    "--force",
    "--package-lock=false",
    ...packages.map((name) => `${name}@${versions[name.startsWith("@opentui/") ? "@opentui/core" : "@resvg/resvg-js"]}`),
  ],
  {
    cwd: root,
    stdout: "inherit",
    stderr: "inherit",
  },
)

if (result.exitCode !== 0) process.exit(result.exitCode)
