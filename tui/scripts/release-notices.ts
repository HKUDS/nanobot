import { readdir, readFile, writeFile } from "node:fs/promises"
import { basename, join } from "node:path"
import { nativePackages, targetPlan } from "./targets"

const target = process.argv[2]
if (!target) throw new Error("target is required")
const plan = targetPlan(target)

const root = join(import.meta.dir, "..")
const projectRoot = join(root, "..")
const asset = plan.executable
const output = join(root, "dist", `${asset}.THIRD_PARTY_NOTICES.txt`)

type PackageNotice = {
  name: string
  version: string
  license: string
  files: Array<{ name: string; content: string }>
}

type PackageManifest = {
  name?: unknown
  version?: unknown
  license?: unknown
  dependencies?: Record<string, string>
  optionalDependencies?: Record<string, string>
  peerDependencies?: Record<string, string>
  devDependencies?: Record<string, string>
}

async function runtimePackageRoots(root: string): Promise<string[]> {
  const manifest = JSON.parse(await readFile(join(root, "package.json"), "utf8")) as PackageManifest
  const nodeModules = join(root, "node_modules")
  const devDependencies = new Set(Object.keys(manifest.devDependencies ?? {}))
  const pending = Object.keys(manifest.dependencies ?? {}).map((name) => ({ name, optional: false }))
  const visited = new Set<string>()
  const roots: string[] = []

  while (pending.length) {
    const next = pending.shift()
    if (!next || visited.has(next.name)) continue
    const { name, optional } = next
    const path = join(nodeModules, name)
    if (!(await Bun.file(join(path, "package.json")).exists())) {
      if (optional) continue
      throw new Error(`required runtime package is missing: ${name}`)
    }
    const dependency = JSON.parse(await readFile(join(path, "package.json"), "utf8")) as PackageManifest
    visited.add(name)
    roots.push(path)
    pending.push(
      ...Object.keys(dependency.dependencies ?? {}).map((dependencyName) => ({
        name: dependencyName,
        optional: false,
      })),
      ...Object.keys(dependency.optionalDependencies ?? {}).map((dependencyName) => ({
        name: dependencyName,
        optional: true,
      })),
      ...Object.keys(dependency.peerDependencies ?? {})
        .filter((peer) => !devDependencies.has(peer))
        .map((peer) => ({ name: peer, optional: true })),
    )
  }
  return roots.sort()
}

async function readPackageNotice(path: string): Promise<PackageNotice> {
  const manifest = JSON.parse(await readFile(join(path, "package.json"), "utf8")) as PackageManifest
  const entries = await readdir(path, { withFileTypes: true })
  const licenseNames = entries
    .filter((entry) => entry.isFile() && /^(licen[cs]e|copying|notice)([._-].*)?$/i.test(entry.name))
    .map((entry) => entry.name)
    .sort()
  if (!licenseNames.length) {
    // These exact npm releases put their MIT declaration in the README only.
    const readme = new Map([
      ["fontkit@2.0.4", "README.md"], ["dfa@1.2.0", "README.md"], ["brotli@1.3.3", "readme.md"],
    ]).get(`${manifest.name}@${manifest.version}`)
    if (readme && manifest.license === "MIT") licenseNames.push(readme)
    else if (typeof manifest.name === "string" && manifest.name.startsWith("@resvg/resvg-js-") && manifest.version === "2.6.2") {
      const wrapper = JSON.parse(await readFile(join(path, "..", "resvg-js", "package.json"), "utf8")) as PackageManifest
      if (wrapper.version !== manifest.version || wrapper.license !== manifest.license) throw new Error("resvg native license version mismatch")
      licenseNames.push("../resvg-js/LICENSE")
    } else throw new Error(`${manifest.name ?? basename(path)} has no license file`)
  }
  return {
    name: String(manifest.name ?? basename(path)),
    version: String(manifest.version ?? "unknown"),
    license: String(manifest.license ?? "see included license"),
    files: await Promise.all(
      licenseNames.map(async (name) => ({ name, content: await readFile(join(path, name), "utf8") })),
    ),
  }
}

const notices = await Promise.all(
  (await runtimePackageRoots(root)).map(readPackageNotice),
)
const packagedNames = new Set(notices.map((notice) => notice.name))
for (const name of nativePackages(plan)) {
  if (!packagedNames.has(name)) throw new Error(`target runtime package is missing: ${name}`)
}
const sections = [
  "nanobot native TUI third-party notices",
  "",
  `Target: ${target}`,
  "Runtime: Bun 1.3.13",
  "The release archive also contains SOURCE_OFFER.md, RELINKING.md, and the complete TUI application source.",
  "fontkit 2.0.4, dfa 1.2.0 and brotli 1.3.3 declare MIT in their included README notices.",
  "resvg's public wrapper and native binding are unmodified; its internal loader is target-selected. MPL-2.0 source is listed in RELINKING.md.",
  "",
  "===== nanobot project license =====",
  "",
  await readFile(join(projectRoot, "LICENSE"), "utf8"),
  "",
  "===== Bun 1.3.13 runtime license and linked-library notice =====",
  "",
  await readFile(join(root, "licenses", "BUN-1.3.13-LICENSE.md"), "utf8"),
  "",
  "===== GNU Lesser General Public License 2.0 =====",
  "",
  await readFile(join(root, "licenses", "LGPL-2.0.txt"), "utf8"),
  "",
  "===== GNU Lesser General Public License 2.1 =====",
  "",
  await readFile(join(root, "licenses", "LGPL-2.1.txt"), "utf8"),
]

for (const notice of notices.sort((left, right) => left.name.localeCompare(right.name))) {
  sections.push("", `===== ${notice.name} ${notice.version} (${notice.license}) =====`)
  for (const file of notice.files) sections.push("", `--- ${file.name} ---`, "", file.content)
}

await writeFile(output, `${sections.join("\n").trimEnd()}\n`, "utf8")
console.log(output)
