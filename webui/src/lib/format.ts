/** Compact token counts for dense runtime metadata (for example, 74.9K). */
export function formatCompactTokenCount(value: number): string {
  if (value < 1_000) return Math.round(value).toLocaleString();
  if (value < 1_000_000) {
    const digits = value < 100_000 ? 1 : 0;
    return `${Number((value / 1_000).toFixed(digits))}K`;
  }
  const digits = value < 100_000_000 ? 1 : 0;
  return `${Number((value / 1_000_000).toFixed(digits))}M`;
}

const LOW_INFORMATION_TITLE_PREVIEWS = new Set([
  "hi",
  "hello",
  "hey",
  "hello nano",
  "hello nanobot",
  "hi nano",
  "hi nanobot",
  "你好",
  "您好",
  "嗨",
  "哈喽",
  "哈啰",
  "在吗",
]);

export function isModelCommandText(text: string | null | undefined): boolean {
  return /^\/model(?:@[A-Za-z0-9_]+)?(?:\s|$)/i.test(text?.trim() ?? "");
}

export function isModelCommandResponseText(text: string | null | undefined): boolean {
  const normalized = text?.trim() ?? "";
  return (
    /^## Model\s+- Current (?:model|selection error):/.test(normalized)
    || normalized.startsWith("Switched model preset to ")
    || normalized.startsWith("Could not switch model preset:")
    || normalized === "Usage: `/model [preset]`"
  );
}

export function visibleSessionPreview(preview: string | null | undefined): string {
  const normalized = preview?.trim() ?? "";
  return isModelCommandText(normalized) || isModelCommandResponseText(normalized) ? "" : normalized;
}

function isLowInformationTitlePreview(text: string): boolean {
  const normalized = text.toLowerCase().replace(/[.!?。！？~～\s]+$/g, "").trim();
  return (
    normalized.startsWith("/") ||
    LOW_INFORMATION_TITLE_PREVIEWS.has(normalized)
  );
}

/** Truncate the first user message into a chat title. */
export function deriveTitle(preview: string | undefined, fallback: string): string {
  if (!preview) return fallback;
  const oneLine = visibleSessionPreview(preview).replace(/\s+/g, " ").trim();
  if (!oneLine) return fallback;
  if (isLowInformationTitlePreview(oneLine)) return fallback;
  return oneLine.length > 60 ? `${oneLine.slice(0, 57)}…` : oneLine;
}
