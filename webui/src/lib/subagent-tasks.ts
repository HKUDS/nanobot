import type { SubagentTaskSnapshot } from "./types";

export interface ObservedSubagentTask extends SubagentTaskSnapshot {
  observedAtMs: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isSubagentTask(value: unknown): value is SubagentTaskSnapshot {
  if (!isRecord(value)) return false;
  const nullableText = (entry: unknown) => entry === null || typeof entry === "string";
  return typeof value.task_id === "string" && value.task_id.length > 0
    && (value.revision === undefined || (typeof value.revision === "number" && Number.isSafeInteger(value.revision) && value.revision >= 0))
    && typeof value.label === "string" && typeof value.task_description === "string"
    && typeof value.phase === "string" && typeof value.state === "string"
    && ["queued", "running", "stopping", "done", "incomplete", "error", "cancelled", "interrupted"].includes(value.state)
    && typeof value.elapsed_seconds === "number" && Number.isFinite(value.elapsed_seconds) && value.elapsed_seconds >= 0
    && typeof value.iteration === "number" && Number.isInteger(value.iteration) && value.iteration >= 0
    && typeof value.created_at === "number" && Number.isFinite(value.created_at)
    && (value.completed_at === null || (typeof value.completed_at === "number" && Number.isFinite(value.completed_at)))
    && nullableText(value.origin_turn_id) && nullableText(value.origin_message_id)
    && nullableText(value.result) && nullableText(value.error) && nullableText(value.stop_reason)
    && typeof value.partial === "boolean"
    && Array.isArray(value.tool_events) && value.tool_events.every((entry: unknown) => isRecord(entry) && typeof entry.name === "string" && typeof entry.status === "string")
    && isRecord(value.receipts) && Object.values(value.receipts).every((entry) => typeof entry === "string" && ["accepted", "delivered", "undelivered"].includes(entry))
    && (value.usage === null || (isRecord(value.usage) && Object.values(value.usage).every((entry) => entry === null || typeof entry === "string" || (typeof entry === "number" && Number.isFinite(entry)))));
}

/** Merge observations from initial reads, live events and control replies. */
export function mergeSubagentTasks(
  current: ObservedSubagentTask[], incoming: SubagentTaskSnapshot[],
): ObservedSubagentTask[] {
  const tasks = new Map(current.map((task) => [task.task_id, task]));
  let changed = false;
  for (const task of incoming) {
    const previous = tasks.get(task.task_id);
    if (previous) {
      const revision = task.revision ?? 0;
      const previousRevision = previous.revision ?? 0;
      if (revision < previousRevision || (revision > 0 && revision === previousRevision)) continue;
      // Read-only hosts predating events have no revision. Their late reads
      // must still respect cancellation and the immutable terminal outcome.
      if (revision === 0 && previousRevision === 0) {
        if (!["queued", "running", "stopping"].includes(previous.state)) continue;
        if (previous.state === "stopping" && ["queued", "running"].includes(task.state)) continue;
        if (previous.state === "running" && task.state === "queued") continue;
      }
    }
    tasks.set(task.task_id, { ...task, observedAtMs: performance.now() });
    changed = true;
  }
  return changed ? [...tasks.values()].sort((a, b) => a.created_at - b.created_at || a.task_id.localeCompare(b.task_id)) : current;
}
