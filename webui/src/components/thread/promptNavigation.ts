import type { UIMessage } from "@/lib/types";

export interface PromptAnchor {
  answerPreview: string;
  id: string;
  label: string;
  preview: string;
  createdAt: number;
  index: number;
}

export function userPromptAnchors(messages: UIMessage[]): PromptAnchor[] {
  let index = 0;
  return messages.flatMap((message, messageIndex) => {
    if (message.role !== "user") return [];
    const anchor: PromptAnchor = {
      answerPreview: nextAssistantPreview(messages, messageIndex),
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
  return truncatePreview(text, 80);
}

export function promptPreview(content: string, index: number): string {
  const text = compactPreview(content);
  if (!text) return `Prompt ${index + 1}`;
  return truncatePreview(text, 320);
}

function nextAssistantPreview(messages: UIMessage[], promptIndex: number): string {
  for (let index = promptIndex + 1; index < messages.length; index += 1) {
    const message = messages[index];
    if (message.role === "user") return "";
    if (message.role !== "assistant") continue;

    const preview = truncatePreview(compactPreview(message.content), 240);
    if (preview) return preview;
  }

  return "";
}

function compactPreview(content: string): string {
  return content.replace(/\n{3,}/g, "\n\n").trim();
}

function truncatePreview(text: string, maxLength: number): string {
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
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
