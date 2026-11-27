import type { SkillsPayload } from "@/lib/types";

export type SkillScope = { chat_id?: string; projectRevision?: string };
export const DEFAULT_SKILL_SCOPE: SkillScope = {};

// Only a gateway chat ID crosses the skill API boundary. The revision is local cache identity.
export function skillScopeParams({ chat_id }: SkillScope): { chat_id?: string } {
  return chat_id ? { chat_id } : {};
}

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

export function notifySkillsChanged(payload: SkillsPayload, scope: SkillScope): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(SKILLS_CHANGED_EVENT, {
    detail: { payload, scope },
  }));
}
