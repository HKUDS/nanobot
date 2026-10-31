import { join } from "node:path"
import { nativePackages, targetPlan } from "./targets"

const target = process.argv[2]
if (!target) throw new Error("target is required")
const packages = nativePackages(targetPlan(target))

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
