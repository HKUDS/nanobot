import { afterEach, expect, test } from "bun:test"
import { cp, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { targetBindings } from "./target-bindings"
import { nativePackages, targetPlan } from "./targets"

const roots: string[] = []
afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })))
})

async function fixture(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "nanobot-target-bindings-"))
  roots.push(root)
  await writeFile(join(root, "package.json"), "{}")
  const wrapper = join(root, "node_modules", "@resvg", "resvg-js")
  await cp(join(import.meta.dir, "..", "node_modules", "@resvg", "resvg-js"), wrapper, { recursive: true })
  for (const name of [
    "resvg-js-win32-x64-msvc", "resvg-js-darwin-arm64", "resvg-js-darwin-x64",
    "resvg-js-linux-x64-gnu", "resvg-js-linux-x64-musl", "resvg-js-linux-arm64-gnu", "resvg-js-linux-arm64-musl",
  ]) {
    const path = join(root, "node_modules", "@resvg", name)
    await mkdir(path, { recursive: true })
    await writeFile(join(path, "package.json"), JSON.stringify({ name: `@resvg/${name}`, version: "2.6.2", main: "index.js" }))
    await writeFile(join(path, "index.js"), `
class Resvg {
  constructor(svg, options) { this.binding = ${JSON.stringify(name)}; this.svg = svg; this.options = JSON.parse(options); }
}
module.exports = { Resvg, renderAsync: async (svg, options) => ({ svg, options: JSON.parse(options) }) };
`)
  }
  return root
}

async function bundle(root: string, target?: string, libc?: "gnu" | "musl") {
  const entry = join(root, "entry.js")
  await writeFile(entry, `
${libc ? `process.report.getReport = () => ({ header: { glibcVersionRuntime: ${libc === "gnu" ? '"2.34"' : "undefined"} } });` : ""}
const { Resvg, renderAsync } = require("@resvg/resvg-js");
const options = { fitTo: { mode: "width", value: 321 } };
console.log(JSON.stringify({ image: new Resvg("<svg/>", options), asyncImage: await renderAsync("<svg/>", options) }));
`)
  const result = await Bun.build({
    entrypoints: [entry],
    outdir: join(root, "out"),
    target: "bun",
    metafile: true,
    plugins: target ? [await targetBindings(targetPlan(target), root)] : [],
  })
  if (!result.success) throw new Error(result.logs.map(String).join("\n"))
  const run = Bun.spawn([process.execPath, join(root, "out", "entry.js")], { stdout: "pipe", stderr: "pipe" })
  const [stdout, stderr, code] = await Promise.all([new Response(run.stdout).text(), new Response(run.stderr).text(), run.exited])
  expect(code, stderr).toBe(0)
  return { value: JSON.parse(stdout), inputs: Object.keys(result.metafile?.inputs ?? {}).map((path) => path.replaceAll("\\", "/")) }
}

test("cross-target binding selection excludes installed host payloads and preserves the public wrapper", async () => {
  const root = await fixture()
  const original = await bundle(root)
  const selected = await bundle(root, "win32-x64")
  // Both host libc variants are installed: the generic loader pulls them into the bundle.
  expect(original.inputs.filter((path) => /resvg-js-linux-x64-.*\/index\.js$/.test(path))).toHaveLength(2)
  expect(selected.inputs.filter((path) => /resvg-js-.*\/index\.js$/.test(path))).toHaveLength(1)
  expect(selected.value).toEqual({
    image: { binding: "resvg-js-win32-x64-msvc", svg: "<svg/>", options: { fitTo: { mode: "width", value: 321 } } },
    asyncImage: { svg: "<svg/>", options: { fitTo: { mode: "width", value: 321 } } },
  })
})

for (const libc of ["gnu", "musl"] as const) {
  test(`Linux target retains both native variants and selects ${libc}`, async () => {
    const root = await fixture()
    const result = await bundle(root, "linux-x64", libc)
    expect(result.value.image.binding).toBe(`resvg-js-linux-x64-${libc}`)
    expect(result.inputs.filter((path) => /resvg-js-linux-x64-.*\/index\.js$/.test(path))).toHaveLength(2)
    expect(nativePackages(targetPlan("linux-x64"))).toEqual([
      "@opentui/core-linux-x64", "@resvg/resvg-js-linux-x64-gnu",
      "@opentui/core-linux-x64-musl", "@resvg/resvg-js-linux-x64-musl",
    ])
  })
}

test("dependency loader changes require an explicit build-adapter review", async () => {
  const root = await fixture()
  await writeFile(join(root, "node_modules", "@resvg", "resvg-js", "js-binding.js"), "module.exports = {}")
  await expect(targetBindings(targetPlan("win32-x64"), root)).rejects.toThrow("js-binding.js changed")
})
