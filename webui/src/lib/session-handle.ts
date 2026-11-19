import type { SessionHandle } from "./types";

export function normalizeSessionHandle(value: unknown, channelSession: boolean): SessionHandle | null {
  if (!value || typeof value !== "object") return null;
  const handle = value as Partial<SessionHandle>;
  const id = typeof handle.id === "string" ? handle.id.trim() : "";
  const rawName = typeof handle.name === "string" ? handle.name : "";
  const name = channelSession ? rawName : rawName.trim();
  if (!/^handle_[a-f0-9]{32}$/i.test(id)) return null;
  if (channelSession ? !/^[a-z]{4}$/.test(name) : !/^[\p{L}\p{N}_-]+$/u.test(name)) return null;
  return { id, name };
}

export function sessionHandleColor(handleId: string): string {
  let hash = 2166136261;
  for (const char of handleId) {
    hash ^= char.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16777619);
  }
  const hue = (hash >>> 0) % 360;
  return `oklch(var(--session-handle-lightness) var(--session-handle-chroma) ${hue})`;
}
