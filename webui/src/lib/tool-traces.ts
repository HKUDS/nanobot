export function formatToolCallTrace(call: unknown): string | null {
  if (!call || typeof call !== "object") return null;
  const item = call as {
    name?: unknown;
    arguments?: unknown;
    function?: { name?: unknown; arguments?: unknown };
  };
  const name =
    typeof item.function?.name === "string"
      ? item.function.name
      : typeof item.name === "string"
        ? item.name
        : "";
  if (!name) return null;
  const args = item.function?.arguments ?? item.arguments;
  if (typeof args === "string" && args.trim()) return `${name}(${args})`;
  if (args && typeof args === "object") return `${name}(${JSON.stringify(args)})`;
  return `${name}()`;
}

export function toolTraceLinesFromEvents(events: unknown): string[] {
  if (!Array.isArray(events)) return [];
  return events
    .filter((event) => {
      if (!event || typeof event !== "object") return false;
      return (event as { phase?: unknown }).phase === "start";
    })
    .map(formatToolCallTrace)
    .filter((trace): trace is string => !!trace);
}
