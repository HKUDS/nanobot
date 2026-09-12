import type { SkillsPayload } from "@/lib/types";

export const SKILLS_CHANGED_EVENT = "nanobot:skills-changed";
export const SKILLS_REFRESH_EVENT = "nanobot:skills-refresh";

export function requestSkillsRefresh(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(SKILLS_REFRESH_EVENT));
}

export function isSkillsPayload(value: unknown): value is SkillsPayload {
  return (
    !!value
    && typeof value === "object"
    && Array.isArray((value as { skills?: unknown }).skills)
  );
}

export function notifySkillsChanged(payload: SkillsPayload): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<SkillsPayload>(SKILLS_CHANGED_EVENT, {
    detail: payload,
  }));
}
