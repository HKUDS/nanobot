export function formatContextWindow(tokens: number): string {
  if (tokens >= 1_000_000) {
    const value = tokens / 1_000_000;
    return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}M`;
  }
  if (tokens >= 1_000) {
    const value = tokens / 1_000;
    return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}K`;
  }
  return String(tokens);
}

export function formatModelContextWindow(tokens: number): string {
  if (tokens === 65_536) return "64K";
  if (tokens === 262_144) return "256K";
  if (tokens === 1_048_576) return "1M";
  return formatContextWindow(tokens);
}
