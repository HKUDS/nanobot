export interface ServerRun {
  run_id: string;
  turn_id: string | null;
  phase: "queued" | "running" | "stopping";
  started_at: number | null;
}

export interface ServerRunSnapshot {
  instance_id: string;
  revision: number;
  runs: readonly ServerRun[];
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function identity(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function turnIdentity(value: unknown): value is string | null {
  return value === null || identity(value);
}

/** Decode only at the host boundary; neither transcript revisions nor clocks are runtime versions. */
export function decodeRunSnapshot(value: unknown): ServerRunSnapshot | null {
  if (!record(value) || !identity(value.instance_id)
    || typeof value.revision !== "number" || !Number.isSafeInteger(value.revision) || value.revision < 0
    || !Array.isArray(value.runs)) return null;
  const runs: ServerRun[] = [];
  const owners = new Set<string>();
  for (const run of value.runs) {
    if (!record(run) || !identity(run.run_id) || !turnIdentity(run.turn_id)
      || (run.phase !== "queued" && run.phase !== "running" && run.phase !== "stopping")
      || (run.started_at !== null && (typeof run.started_at !== "number" || !Number.isFinite(run.started_at)))
      || owners.has(run.run_id)) return null;
    owners.add(run.run_id);
    runs.push({ run_id: run.run_id, turn_id: run.turn_id, phase: run.phase, started_at: run.started_at });
  }
  return { instance_id: value.instance_id, revision: value.revision, runs };
}
