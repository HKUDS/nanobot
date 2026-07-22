export function compactReasoningPreview(value: string): string {
  return value
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/[*_#`~]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}
