export function sessionHandleColor(handleId: string): string {
  let hash = 2166136261;
  for (const char of handleId) {
    hash ^= char.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16777619);
  }
  const hue = (hash >>> 0) % 360;
  return `oklch(var(--session-handle-lightness) var(--session-handle-chroma) ${hue})`;
}
