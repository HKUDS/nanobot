// The embedded UI may ask to open the host menu, never execute SSH actions.
// Host lists, paths and credentials remain exclusively in the local shell.
export const HOST_BRIDGE = "nanobot.host-navigation.v1";
export interface HostAnchor { left: number; top: number; width: number; height: number }
export interface EmbeddedHost { name: string; hostname: string; pendingName?: string; error?: string }

export function isLocalShellOrigin(origin: string): boolean {
  try {
    const url = new URL(origin);
    return url.origin === origin && ["http:", "https:"].includes(url.protocol)
      && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  } catch { return false; }
}

export function bridgeMessage(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const message = value as Record<string, unknown>;
  return message.channel === HOST_BRIDGE && typeof message.type === "string" ? message : null;
}

export function readEmbeddedHost(message: Record<string, unknown>): EmbeddedHost | null {
  return typeof message.name === "string" && message.name.length > 0 && message.name.length <= 120
    && typeof message.hostname === "string" && message.hostname.length <= 255
    && (message.pendingName === undefined || typeof message.pendingName === "string" && message.pendingName.length <= 120)
    && (message.error === undefined || typeof message.error === "string" && message.error.length <= 1024)
    ? { name: message.name, hostname: message.hostname, pendingName: message.pendingName as string | undefined, error: message.error as string | undefined } : null;
}

export function readHostAnchor(value: unknown): HostAnchor | null {
  if (!value || typeof value !== "object") return null;
  const rect = value as Record<string, unknown>;
  return ["left", "top", "width", "height"].every((key) => typeof rect[key] === "number"
    && Number.isFinite(rect[key]) && Math.abs(rect[key] as number) <= 100_000)
    && (rect.width as number) > 0 && (rect.height as number) > 0
    ? { left: rect.left as number, top: rect.top as number, width: rect.width as number, height: rect.height as number } : null;
}
