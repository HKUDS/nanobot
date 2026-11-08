import type { SandboxCheck } from "./types";

/** Names come from the gateway's supported backend, never the browser's OS. */
export function sandboxLauncherDisplay(backend: SandboxCheck["supported_backend"] | undefined) {
  if (backend === "bwrap") return { name: "Bubblewrap (bwrap)", executable: "bwrap" };
  if (backend === "seatbelt") return { name: "macOS Seatbelt (sandbox-exec)", executable: "sandbox-exec" };
  return null;
}
