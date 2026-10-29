import type { ToolProgressEvent } from "@/lib/types";

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
  if (args && typeof args === "object") {
    const serialized = JSON.stringify(args);
    return serialized === "{}" || serialized === "[]" ? `${name}()` : `${name}(${serialized})`;
  }
  return `${name}()`;
}

export function canonicalToolTrace(line: string): string {
  const trimmed = line.trim();
  const match = /^([a-zA-Z0-9_.-]+)\((.*)\)$/.exec(trimmed);
  if (!match) return trimmed;
  const args = match[2].trim();
  if (!args) return `${match[1]}()`;
  try {
    return `${match[1]}(${JSON.stringify(JSON.parse(args))})`;
  } catch {
    return trimmed;
  }
}

const VALID_PHASES = new Set(["start", "update", "end", "error"]);
const PHASE_RANK: Record<string, number> = { start: 1, update: 1, end: 2, error: 3 };

export function normalizeToolProgressEvents(events: unknown): ToolProgressEvent[] {
  if (!Array.isArray(events)) return [];
  const out: ToolProgressEvent[] = [];
  for (const event of events) {
    if (!event || typeof event !== "object") continue;
    const record = event as ToolProgressEvent;
    const phase = record.phase;
    if (!(phase && typeof phase === "string" && VALID_PHASES.has(phase))) continue;
    const name = typeof record.name === "string" ? record.name : "";
    const functionName =
      typeof (record as { function?: { name?: unknown } }).function?.name === "string"
        ? String((record as { function?: { name?: unknown } }).function?.name)
        : "";
    if (!name && !functionName) continue;
    if (record.execution !== undefined) {
      const facts = record.execution;
      if (!facts || typeof facts !== "object"
        || !["running", "stopping", "succeeded", "failed", "cancelled", "timed_out"].includes(facts.state)
        || typeof facts.observed_at !== "number" || !Number.isFinite(facts.observed_at)
        || !Number.isInteger(facts.sequence) || facts.sequence < 1
        || !(facts.exit_code === null || typeof facts.exit_code === "number" && Number.isInteger(facts.exit_code))
        || !(facts.finish_reason === null || typeof facts.finish_reason === "string")
        || typeof facts.output_incomplete !== "boolean"
        || !Number.isInteger(facts.truncated_chars) || facts.truncated_chars < 0) continue;
    }
    out.push(record);
  }
  return out;
}

function toolEventKey(event: ToolProgressEvent): string {
  if (event.call_id) return `call:${event.call_id}`;
  return formatToolCallTrace(event) ?? JSON.stringify(event);
}

export function mergeToolProgressEvents(
  previous: ToolProgressEvent[] | undefined,
  incoming: ToolProgressEvent[],
): ToolProgressEvent[] {
  if (!previous?.length) return incoming;
  if (!incoming.length) return previous;
  const next = [...previous];
  const indexByKey = new Map(next.map((event, index) => [toolEventKey(event), index]));
  for (const event of incoming) {
    const key = toolEventKey(event);
    const existingIndex = indexByKey.get(key);
    if (existingIndex === undefined) {
      indexByKey.set(key, next.length);
      next.push(event);
      continue;
    }
    const existing = next[existingIndex];
    const incomingRank = PHASE_RANK[String(event.phase)] ?? 0;
    const existingRank = PHASE_RANK[String(existing.phase)] ?? 0;
    const olderObservation = existing.execution && event.execution
      && event.execution.sequence < existing.execution.sequence;
    next[existingIndex] = !olderObservation && incomingRank >= existingRank
      ? { ...existing, ...event }
      : existing;
  }
  return next;
}

export function toolTraceLinesFromEvents(events: unknown): string[] {
  const seen = new Set<string>();
  const lines: string[] = [];
  for (const event of normalizeToolProgressEvents(events)) {
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
  const seen = new Set(previousTraces.map(canonicalToolTrace));
  const traces = [...previousTraces];
  let added = false;
  for (const line of lines) {
    const key = canonicalToolTrace(line);
    if (seen.has(key)) continue;
    seen.add(key);
    traces.push(line);
    added = true;
  }
  return { traces, added };
}

export function mergeToolProgressTraceLines(
  previousTraces: string[],
  previousEvents: ToolProgressEvent[] | undefined,
  incomingTraces: string[],
  incomingEvents: ToolProgressEvent[],
): string[] {
  const mergedEvents = mergeToolProgressEvents(previousEvents, incomingEvents);
  const candidates = mergeUniqueToolTraceLines(previousTraces, incomingTraces).traces;
  const eventTraceKeys = new Set([
    ...toolTraceLinesFromEvents(previousEvents),
    ...toolTraceLinesFromEvents(incomingEvents),
  ].map(canonicalToolTrace));
  const nonEventTraces = candidates.filter(
    (line) => !eventTraceKeys.has(canonicalToolTrace(line)),
  );
  const eventTraces = toolTraceLinesFromEvents(mergedEvents);
  if (mergedEvents.some((event) => event.execution)) {
    // Public observation rows were already merged by call ID, not display text.
    return [...nonEventTraces, ...eventTraces];
  }
  return mergeUniqueToolTraceLines(nonEventTraces, eventTraces).traces;
}
