import { join } from "node:path"

const packagesByTarget: Record<string, string[]> = {
  "darwin-arm64": ["@opentui/core-darwin-arm64"],
  "darwin-x64": ["@opentui/core-darwin-x64"],
  "linux-arm64": ["@opentui/core-linux-arm64", "@opentui/core-linux-arm64-musl"],
  "linux-x64": ["@opentui/core-linux-x64", "@opentui/core-linux-x64-musl"],
  "win32-x64": ["@opentui/core-win32-x64"],
}

const target = process.argv[2]
if (!target) throw new Error("target is required")
const packages = packagesByTarget[target]
if (!packages) throw new Error(`unsupported target: ${target}`)

const root = join(import.meta.dir, "..")
const manifest = await Bun.file(join(root, "package.json")).json()
const version = manifest.dependencies?.["@opentui/core"]
if (typeof version !== "string" || !/^\d+\.\d+\.\d+$/.test(version)) {
  throw new Error("@opentui/core must use an exact version")
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
    ...packages.map((name) => `${name}@${version}`),
  ],
  {
    cwd: root,
    stdout: "inherit",
    stderr: "inherit",
  },
)

if (result.exitCode !== 0) process.exit(result.exitCode)
