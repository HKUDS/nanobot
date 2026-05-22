/** Drop duplicate tool_call objects (same id or identical formatted trace). */
export function dedupeToolCallsForUi(calls: unknown): unknown[] {
  if (!Array.isArray(calls) || calls.length === 0) return [];
  const seen = new Set<string>();
  const out: unknown[] = [];
  for (const c of calls) {
    let key: string | null = null;
    if (c && typeof c === "object" && "id" in c) {
      const id = (c as { id?: unknown }).id;
      if (typeof id === "string" && id.length > 0) key = `id:${id}`;
    }
    if (key == null) {
      key = formatToolCallTrace(c) ?? "";
    }
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(c);
  }
  return out;
}

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

const VALID_PHASES = new Set(["start", "end", "error"]);

export function toolTraceLinesFromEvents(events: unknown): string[] {
  if (!Array.isArray(events)) return [];
  const seen = new Set<string>();
  const lines: string[] = [];
  for (const event of events) {
    if (!event || typeof event !== "object") continue;
    const phase = (event as { phase?: unknown }).phase;
    if (!(phase && typeof phase === "string" && VALID_PHASES.has(phase))) continue;
    const callId = (event as { call_id?: unknown }).call_id;
    if (callId && typeof callId === "string") {
      if (seen.has(callId)) continue;
      seen.add(callId);
    }
    const line = formatToolCallTrace(event);
    if (!line) continue;
    lines.push(line);
  }
  return lines;
}

export function mergeUniqueToolTraceLines(
  previousTraces: string[],
  lines: string[],
): { traces: string[]; added: boolean } {
  const seen = new Set(previousTraces);
  const traces = [...previousTraces];
  let added = false;
  for (const line of lines) {
    if (seen.has(line)) continue;
    seen.add(line);
    traces.push(line);
    added = true;
  }
  return { traces, added };
}
