type NativePair = Readonly<{ opentui: string; resvg: string }>

type TargetSpec = Readonly<{
  bunTarget: Bun.Build.CompileTarget
  executableBudgetBytes: number
}> & (
  | { platform: "linux"; bindings: { gnu: NativePair; musl: NativePair } }
  | { platform: "darwin" | "win32"; bindings: { native: NativePair } }
)

const MiB = 1024 * 1024
// Wheels cannot select CPU features: every x64 target uses Bun's baseline runtime.
// Unmeasured arm64/macOS targets retain the existing 150 MiB archive limit.
const targets = {
  "darwin-arm64": {
    platform: "darwin", bunTarget: "bun-darwin-arm64", executableBudgetBytes: 150 * MiB,
    bindings: { native: { opentui: "@opentui/core-darwin-arm64", resvg: "@resvg/resvg-js-darwin-arm64" } },
  },
  "darwin-x64": {
    platform: "darwin", bunTarget: "bun-darwin-x64-baseline", executableBudgetBytes: 150 * MiB,
    bindings: { native: { opentui: "@opentui/core-darwin-x64", resvg: "@resvg/resvg-js-darwin-x64" } },
  },
  "linux-arm64": {
    platform: "linux", bunTarget: "bun-linux-arm64", executableBudgetBytes: 150 * MiB,
    bindings: {
      gnu: { opentui: "@opentui/core-linux-arm64", resvg: "@resvg/resvg-js-linux-arm64-gnu" },
      musl: { opentui: "@opentui/core-linux-arm64-musl", resvg: "@resvg/resvg-js-linux-arm64-musl" },
    },
  },
  "linux-x64": {
    platform: "linux", bunTarget: "bun-linux-x64-baseline", executableBudgetBytes: 135 * MiB,
    bindings: {
      gnu: { opentui: "@opentui/core-linux-x64", resvg: "@resvg/resvg-js-linux-x64-gnu" },
      musl: { opentui: "@opentui/core-linux-x64-musl", resvg: "@resvg/resvg-js-linux-x64-musl" },
    },
  },
  "win32-x64": {
    platform: "win32", bunTarget: "bun-windows-x64-baseline", executableBudgetBytes: 135 * MiB,
    bindings: { native: { opentui: "@opentui/core-win32-x64", resvg: "@resvg/resvg-js-win32-x64-msvc" } },
  },
} as const satisfies Record<string, TargetSpec>

export type TargetPlan = TargetSpec & { id: keyof typeof targets; executable: string }

export function targetPlan(raw: string): TargetPlan {
  if (!Object.hasOwn(targets, raw)) throw new Error(`unsupported target: ${raw}`)
  const id = raw as keyof typeof targets
  const spec = targets[id]
  return { ...spec, id, executable: `nanobot-tui-${id}${spec.platform === "win32" ? ".exe" : ""}` }
}

export function nativePackages(plan: TargetPlan): string[] {
  return Object.values(plan.bindings).flatMap((pair: NativePair) => [pair.opentui, pair.resvg])
}
