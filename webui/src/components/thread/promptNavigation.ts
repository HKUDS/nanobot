import type { UIMessage } from "@/lib/types";

export interface PromptAnchor {
  id: string;
  label: string;
  preview: string;
  createdAt: number;
  index: number;
}

export function userPromptAnchors(messages: UIMessage[]): PromptAnchor[] {
  let index = 0;
  return messages.flatMap((message) => {
    if (message.role !== "user") return [];
    const anchor: PromptAnchor = {
      id: message.id,
      label: promptLabel(message.content, index),
      preview: promptPreview(message.content, index),
      createdAt: message.createdAt,
      index,
    };
    index += 1;
    return [anchor];
  });
}

export function promptLabel(content: string, index: number): string {
  const text = content.replace(/\s+/g, " ").trim();
  if (!text) return `Prompt ${index + 1}`;
  return text.length > 80 ? `${text.slice(0, 77)}...` : text;
}

export function promptPreview(content: string, index: number): string {
  const text = content.replace(/\n{3,}/g, "\n\n").trim();
  if (!text) return `Prompt ${index + 1}`;
  return text.length > 320 ? `${text.slice(0, 317)}...` : text;
}

export function jumpToPrompt(scrollEl: HTMLElement | null, promptId: string | undefined): void {
  if (!scrollEl || !promptId) return;
  const target = findPromptElement(scrollEl, promptId);
  if (!target) return;
  scrollEl.scrollTo({
    top: Math.max(0, promptTop(scrollEl, target) - 16),
    behavior: "smooth",
  });
}

export function findPromptElement(scrollEl: HTMLElement, promptId: string): HTMLElement | null {
  const candidates = scrollEl.querySelectorAll<HTMLElement>("[data-user-prompt-id]");
  return Array.from(candidates).find(
    (candidate) => candidate.dataset.userPromptId === promptId,
  ) ?? null;
}

export function promptTop(scrollEl: HTMLElement, target: HTMLElement): number {
  const scrollRect = scrollEl.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  const hasLayoutRect = scrollRect.top !== 0 || targetRect.top !== 0;
  if (hasLayoutRect) {
    return targetRect.top - scrollRect.top + scrollEl.scrollTop;
  }
  return target.offsetTop;
}
