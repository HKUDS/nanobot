import { fetchWithTimeout } from "@/lib/http";
import type { WebUIMutationTransport } from "@/lib/api";
import { parseCodexQuota } from "../../../packages/client-events/operations";

export { quotaDuration, quotaSummary } from "../../../packages/client-events/operations";
export type { CodexQuotaSnapshot } from "../../../packages/client-events/operations";

export interface DevelopmentJob {
  id: string;
  title: string;
  objective: string;
  stage: string;
  acceptance: string[];
  notes: string[];
  blocked_reason: string | null;
  review: string | null;
  review_accepted: boolean;
  verification: Array<{ exit_code: number; source_sha256: string }>;
}

export interface DevelopmentPayload {
  enabled: boolean;
  message?: string | null;
  project: {
    objective: string;
    paused: boolean;
    requirements: Array<{ id: string; description: string }>;
    jobs: DevelopmentJob[];
  } | null;
}

async function read(path: string, token: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetchWithTimeout(path, { headers: { Authorization: `Bearer ${token}` }, signal }, 25_000);
  if (!response.ok) throw new Error(`Odczyt nie powiódł się (${response.status}).`);
  return response.json();
}

export async function fetchCodexLimits(token: string, signal?: AbortSignal) {
  return parseCodexQuota(await read("/api/webui/codex-limits", token, signal));
}

function development(value: unknown): DevelopmentPayload {
  if (!value || typeof value !== "object" || !("enabled" in value) || typeof value.enabled !== "boolean"
      || !("project" in value)) throw new Error("Niepoprawny stan rozwoju.");
  if (value.project !== null) {
    const project = value.project;
    if (!project || typeof project !== "object" || !("objective" in project) || typeof project.objective !== "string"
        || !("paused" in project) || typeof project.paused !== "boolean"
        || !("jobs" in project) || !Array.isArray(project.jobs)
        || !("requirements" in project) || !Array.isArray(project.requirements)) {
      throw new Error("Niepoprawny projekt rozwoju.");
    }
    for (const job of project.jobs) {
      if (!job || typeof job.id !== "string" || typeof job.title !== "string" || typeof job.stage !== "string"
          || !Array.isArray(job.acceptance) || !Array.isArray(job.notes) || !Array.isArray(job.verification)) {
        throw new Error("Niepoprawny zapis zadania rozwoju.");
      }
    }
  }
  return value as DevelopmentPayload;
}

export async function fetchDevelopment(token: string, signal?: AbortSignal): Promise<DevelopmentPayload> {
  return development(await read("/api/webui/development", token, signal));
}

export async function controlDevelopment(client: WebUIMutationTransport, action: string, jobId?: string): Promise<DevelopmentPayload> {
  return development(await client.requestMutation("development.control", { action, ...(jobId ? { job_id: jobId } : {}) }));
}
