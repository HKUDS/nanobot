import { chmod, mkdir } from "node:fs/promises"
import { basename, join } from "node:path"

const target = process.argv[2] || `${process.platform}-${process.arch}`
const [platform, arch] = target.split("-")

if (!platform || !arch || !["darwin", "linux", "win32"].includes(platform)) {
  throw new Error(`unsupported target: ${target}`)
}

const bunPlatform = platform === "win32" ? "windows" : platform
const extension = platform === "win32" ? ".exe" : ""
const outputDir = join(import.meta.dir, "..", "dist")
const output = join(outputDir, `nanobot-tui-${platform}-${arch}${extension}`)

await mkdir(outputDir, { recursive: true })
const result = await Bun.build({
  entrypoints: [join(import.meta.dir, "..", "src", "index.ts")],
  compile: {
    target: `bun-${bunPlatform}-${arch}` as Bun.Build.CompileTarget,
    outfile: output,
  },
})

if (!result.success) {
  for (const log of result.logs) console.error(log)
  process.exit(1)
}
if (platform !== "win32") await chmod(output, 0o755)
const digest = new Bun.CryptoHasher("sha256")
  .update(await Bun.file(output).arrayBuffer())
  .digest("hex")
await Bun.write(`${output}.sha256`, `${digest}  ${basename(output)}\n`)
console.log(output)
