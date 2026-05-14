import type { TFunction } from "i18next";

import type { LongTaskAgentUIData } from "@/lib/types";

export const EVENT_I18N_KEY: Record<string, string> = {
  task_start: "message.longTaskEvTaskStart",
  step_start: "message.longTaskEvStepStart",
  step_complete: "message.longTaskEvStepComplete",
  handoff_received: "message.longTaskEvHandoff",
  validation_started: "message.longTaskEvValidationStarted",
  validation_failed: "message.longTaskEvValidationFailed",
  validation_passed: "message.longTaskEvValidationPassed",
  task_complete: "message.longTaskEvTaskComplete",
  task_error: "message.longTaskEvTaskError",
};

export function totalSteps(data: LongTaskAgentUIData): number {
  const x = data.total_steps ?? data.max_steps;
  if (typeof x !== "number" || x <= 0) return 0;
  return x;
}

export function displayStep1Based(data: LongTaskAgentUIData): number {
  const tot = totalSteps(data);
  const idx = data.step ?? data.current_step ?? 0;
  const i = typeof idx === "number" ? idx : 0;
  if (data.event === "task_error" && data.event_error === "Max steps reached") {
    return tot > 0 ? tot : i > 0 ? i : 1;
  }
  return i + 1;
}

export function snapshotMarkdownBody(s: LongTaskAgentUIData): string {
  const h = s.step_handoff ?? s.last_handoff;
  const chunks: string[] = [];
  const msg = (h?.message ?? "").trim();
  if (msg) chunks.push(msg);
  const summ = (s.summary ?? "").trim();
  if (summ) chunks.push(summ);
  if (s.reason?.trim() && s.event === "validation_failed") {
    chunks.push(s.reason.trim());
  }
  if (s.event_error?.trim() && s.event === "task_error") {
    chunks.push(s.event_error.trim());
  }
  const hint = (h?.next_step_hint ?? "").trim();
  if (hint) chunks.push(`**Next:** ${hint}`);
  const ver = (h?.verification ?? "").trim();
  if (ver) chunks.push(`**Checks:** ${ver}`);
  return chunks.join("\n\n");
}

export function stepChipLabel(
  snap: LongTaskAgentUIData,
  step1: number,
  tot: number,
  t: TFunction,
): string {
  if (tot > 0) return t("message.longTaskStepChip", { step: step1, total: tot });
  return snap.event;
}

export function collapsedSummaryLine(
  data: LongTaskAgentUIData,
  fallbackText: string,
  t: TFunction,
): string {
  const u = (data.ui_summary ?? "").trim();
  if (u) return u;
  const g = (data.goal ?? "").trim();
  if (g.length > 52) return `${g.slice(0, 49)}…`;
  if (g) return g;
  return fallbackText.trim() || t("message.longTaskSubtitleWorking");
}
