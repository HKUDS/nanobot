import { chmod, mkdir } from "node:fs/promises"
import { basename, join } from "node:path"
import { targetBindings } from "./target-bindings"
import { nativePackages, targetPlan } from "./targets"

const plan = targetPlan(process.argv[2] || `${process.platform}-${process.arch}`)
const root = join(import.meta.dir, "..")
const outputDir = join(root, "dist")
const output = join(outputDir, plan.executable)

await mkdir(outputDir, { recursive: true })
const result = await Bun.build({
  entrypoints: [join(import.meta.dir, "..", "src", "index.ts")],
  define: { NANOBOT_COMPILED: "true" },
  // Standalone files retain JS; the optional precompiled cache costs another ~22 MiB on x64.
  bytecode: false,
  format: "esm",
  plugins: [await targetBindings(plan, root)],
  minify: { whitespace: true, syntax: true, identifiers: true, keepNames: true },
  compile: {
    target: plan.bunTarget,
    outfile: output,
  },
})

if (!result.success) {
  for (const log of result.logs) console.error(log)
  process.exit(1)
}
if (plan.platform !== "win32") await chmod(output, 0o755)
const bytes = Bun.file(output).size
const digest = new Bun.CryptoHasher("sha256")
  .update(await Bun.file(output).arrayBuffer())
  .digest("hex")
await Bun.write(`${output}.sha256`, `${digest}  ${basename(output)}\n`)
await Bun.write(`${output}.size.json`, JSON.stringify({
  phase: "compiled", // macOS signing happens later; the archive manifest owns final hashes.
  target: plan.id,
  bunTarget: plan.bunTarget,
  bunVersion: Bun.version,
  bunRevision: Bun.revision,
  bytecode: false,
  executable: basename(output),
  bytes,
  sha256: digest,
  budgetBytes: plan.executableBudgetBytes,
  expectedNativePackages: nativePackages(plan),
}, null, 2) + "\n")
if (bytes > plan.executableBudgetBytes) {
  throw new Error(`${plan.id} executable is ${bytes} bytes; budget is ${plan.executableBudgetBytes}`)
}
console.log(output)
