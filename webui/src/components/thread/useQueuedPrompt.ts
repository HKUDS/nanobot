import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from "react";

import { isLocalAttachment } from "../../../../packages/client-events/attachments";
import type { AttachedImage, RestoredReadyImage } from "@/hooks/useAttachedImages";
import type { SendAttachment, SendOptions } from "@/hooks/useNanobotStream";
import type { SessionMention } from "@/lib/types";

const QUEUED_PROMPTS_STORAGE_PREFIX = "nanobot.webui.composerQueuedGuidance.v1:";
const EMPTY_COMPLETED_TURN_IDS: readonly string[] = [];
const QUEUED_PROMPTS_LIMIT = 20;

type QueuedPromptImage = RestoredReadyImage;

export interface QueuedPromptContent {
  text: string;
  images?: QueuedPromptImage[];
  quotedContext?: string;
  sessionMentions?: SessionMention[];
}

interface QueuedPrompt extends QueuedPromptContent {
  id: string;
  autoAfterTurnId?: string;
  autoPaused?: boolean;
  autoSendPageId?: string;
}

let queuedPromptPageId: string | undefined;

function getQueuedPromptPageId(): string {
  return queuedPromptPageId ??= crypto.randomUUID();
}

function canAutoSendQueuedPrompt(prompt: QueuedPrompt): boolean {
  return !prompt.autoPaused && prompt.autoSendPageId === getQueuedPromptPageId();
}

function pauseQueuedPrompt(prompt: QueuedPrompt): QueuedPrompt {
  return { ...prompt, autoAfterTurnId: undefined, autoSendPageId: undefined, autoPaused: true };
}

function mergeQueuedPrompt(first: QueuedPrompt, next: QueuedPrompt): QueuedPrompt {
  const prompts = [first, next];
  const mentions = new Map<string, SessionMention>();
  for (const prompt of prompts) {
    for (const mention of prompt.sessionMentions ?? []) {
      if (!mentions.has(mention.session_key)) mentions.set(mention.session_key, mention);
    }
  }
  return {
    id: first.id,
    text: prompts.map((prompt) => prompt.text).filter(Boolean).join("\n"),
    images: prompts.flatMap((prompt) => prompt.images ?? []),
    quotedContext: [...new Set(prompts.map((prompt) => prompt.quotedContext).filter(Boolean))].join("\n\n"),
    sessionMentions: [...mentions.values()],
    autoAfterTurnId: first.autoAfterTurnId,
    autoPaused: prompts.some((prompt) => prompt.autoPaused),
    autoSendPageId: first.autoSendPageId,
  };
}

function queuedPromptsStorageKey(key: string | null): string | null {
  const clean = key?.trim();
  return clean ? `${QUEUED_PROMPTS_STORAGE_PREFIX}${clean}` : null;
}

function normalizeQueuedSessionMentions(value: unknown): SessionMention[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const candidate = item as Partial<SessionMention>;
    const name = candidate.name?.trim().slice(0, 80);
    const sessionKey = candidate.session_key?.trim().slice(0, 512);
    if (
      !name
      || !sessionKey?.startsWith("websocket:")
      || !/^[\p{L}\p{N}_-]+$/u.test(name)
    ) return [];
    return [{
      ...(typeof candidate.id === "string" && /^handle_[a-f0-9]{32}$/i.test(candidate.id)
        ? { id: candidate.id }
        : {}),
      name,
      session_key: sessionKey,
      title: candidate.title?.trim().slice(0, 160) ?? "",
    }];
  });
}

function normalizeQueuedPrompt(item: unknown, index: number): QueuedPrompt | null {
  if (!item || typeof item !== "object") return null;
  const record = item as Partial<QueuedPrompt>;
  if (typeof record.text !== "string") return null;
  const text = record.text.trim();
  const images = Array.isArray(record.images)
    ? record.images.flatMap((image): QueuedPromptImage[] => {
        if (!image || typeof image !== "object") return [];
        const candidate = image as Partial<QueuedPromptImage>;
        if (isLocalAttachment(candidate.local)) {
          return [{ local: candidate.local, kind: candidate.local.kind, name: candidate.local.name }];
        }
        if (typeof candidate.dataUrl !== "string" || !candidate.dataUrl.startsWith("data:")) {
          return [];
        }
        const kind = candidate.kind === "file" || candidate.kind === "image" || candidate.kind === "video"
          ? candidate.kind
          : candidate.dataUrl.startsWith("data:image/")
            ? "image"
            : "file";
        return [{
          dataUrl: candidate.dataUrl,
          kind,
          ...(typeof candidate.name === "string" && candidate.name.trim()
            ? { name: candidate.name.trim() }
            : {}),
        }];
      })
    : [];
  const quotedContext = typeof record.quotedContext === "string"
    ? record.quotedContext.trim()
    : "";
  const sessionMentions = normalizeQueuedSessionMentions(record.sessionMentions);
  if (!text && images.length === 0) return null;
  const id = typeof record.id === "string" && record.id.trim()
    ? record.id
    : `queued-prompt-restored-${index}`;
  const prompt: QueuedPrompt = {
    id,
    text,
    ...(images.length > 0 ? { images } : {}),
    ...(quotedContext ? { quotedContext } : {}),
    ...(sessionMentions.length > 0 ? { sessionMentions } : {}),
    ...(typeof record.autoAfterTurnId === "string" && record.autoAfterTurnId.trim()
      ? { autoAfterTurnId: record.autoAfterTurnId.trim() }
      : {}),
    ...(record.autoPaused === true ? { autoPaused: true } : {}),
    ...(typeof record.autoSendPageId === "string" ? { autoSendPageId: record.autoSendPageId } : {}),
  };
  return canAutoSendQueuedPrompt(prompt) ? prompt : pauseQueuedPrompt(prompt);
}

function readQueuedPrompt(storageKey: string): QueuedPrompt | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(storageKey);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return null;
    return parsed.slice(0, QUEUED_PROMPTS_LIMIT)
      .map((item, index) => normalizeQueuedPrompt(item, index))
      .filter((item): item is QueuedPrompt => item != null)
      .reduce<QueuedPrompt | null>((pending, prompt) => (
        pending ? mergeQueuedPrompt(pending, prompt) : prompt
      ), null);
  } catch {
    return null;
  }
}

function storeQueuedPrompt(storageKey: string, prompt: QueuedPrompt | null): void {
  if (typeof window === "undefined") return;
  try {
    if (!prompt) {
      window.localStorage.removeItem(storageKey);
      return;
    }
    // Retain the v1 array shape so existing queued drafts remain readable.
    window.localStorage.setItem(storageKey, JSON.stringify([prompt]));
  } catch {
    // localStorage persistence is a convenience; the in-memory draft still works.
  }
}

interface QueuedPromptSnapshot {
  prompt: QueuedPrompt | null;
  sending: boolean;
  error: string | null;
}

// Delivery can outlive the composer during attachment upload or topic navigation.
// Keep one owner per mounted/sending topic; idle, unmounted owners are reloaded from storage.
const queuedPromptStores = new Map<string, QueuedPromptStore>();

class QueuedPromptStore {
  private snapshot: QueuedPromptSnapshot;
  private listeners = new Set<() => void>();

  constructor(private storageKey: string | null) {
    this.snapshot = { prompt: storageKey ? readQueuedPrompt(storageKey) : null, sending: false, error: null };
  }

  getSnapshot = () => this.snapshot;

  subscribe = (listener: () => void) => {
    if (this.storageKey) queuedPromptStores.set(this.storageKey, this);
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
      this.release();
    };
  };

  private release() {
    if (this.storageKey && !this.snapshot.sending && this.listeners.size === 0
      && queuedPromptStores.get(this.storageKey) === this) queuedPromptStores.delete(this.storageKey);
  }

  private publish(next: QueuedPromptSnapshot) {
    if (this.storageKey && next.prompt !== this.snapshot.prompt) storeQueuedPrompt(this.storageKey, next.prompt);
    this.snapshot = next;
    for (const listener of this.listeners) listener();
    this.release();
  }

  set = (next: QueuedPrompt | null | ((current: QueuedPrompt | null) => QueuedPrompt | null)) => {
    const prompt = typeof next === "function" ? next(this.snapshot.prompt) : next;
    if (prompt !== this.snapshot.prompt) this.publish({ ...this.snapshot, prompt, error: null });
  };

  send(prompt: QueuedPrompt, send: () => void | boolean | Promise<void | boolean>) {
    if (this.snapshot.sending) return;
    const retained = pauseQueuedPrompt(prompt);
    this.publish({ prompt: retained, sending: true, error: null });
    const finish = (accepted: void | boolean, error?: unknown) => {
      const failed = accepted === false || error !== undefined;
      this.publish({
        prompt: failed ? retained : null,
        sending: false,
        error: failed ? error instanceof Error ? error.message : "Message not sent; queued draft retained" : null,
      });
    };
    try {
      const result = send();
      if (result instanceof Promise) void result.then((accepted) => finish(accepted), (error: unknown) => finish(false, error));
      else finish(result);
    } catch (error) {
      finish(false, error);
    }
  }
}

function queuedPromptStoreFor(storageKey: string | null): QueuedPromptStore {
  if (!storageKey) return new QueuedPromptStore(null);
  let store = queuedPromptStores.get(storageKey);
  if (!store) {
    store = new QueuedPromptStore(storageKey);
    queuedPromptStores.set(storageKey, store);
  }
  return store;
}

function expireQueuedPromptAuthorization(): void {
  queuedPromptPageId = undefined;
  for (const store of queuedPromptStores.values()) {
    store.set((prompt) => prompt && !prompt.autoPaused ? pauseQueuedPrompt(prompt) : prompt);
  }
}

// Saved content survives a page's lifetime; permission to execute it does not.
if (typeof window !== "undefined") {
  window.addEventListener("pagehide", expireQueuedPromptAuthorization);
  document.addEventListener("freeze", expireQueuedPromptAuthorization);
}

export function queuedUploadBytes(image: QueuedPromptImage): number {
  if (image.local) return 0;
  const dataUrl = image.dataUrl ?? "";
  const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return Math.floor(base64.length * 3 / 4) - padding;
}

export function readyImagesToQueuedImages(
  images: AttachedImage[],
): QueuedPromptImage[] {
  return images.map((img) => ({
    dataUrl: img.dataUrl,
    local: img.local,
    kind: img.kind,
    name: img.file.name,
  }));
}

export function queuedImagesToSendImages(images?: QueuedPromptImage[]): SendAttachment[] | undefined {
  if (!images?.length) return undefined;
  return images.flatMap((img): SendAttachment[] => {
    if (img.local) return [{
      media: { path: img.local.path, name: img.local.name },
      preview: { kind: img.local.kind, url: img.local.url, name: img.local.name },
    }];
    if (!img.dataUrl) return [];
    return [{
      media: { data_url: img.dataUrl, ...(img.name ? { name: img.name } : {}) },
      preview: {
        kind: img.kind ?? (img.dataUrl.startsWith("data:image/") ? "image" : img.dataUrl.startsWith("data:video/") ? "video" : "file"),
        url: img.dataUrl, ...(img.name ? { name: img.name } : {}),
      },
    }];
  });
}

interface QueuedPromptRun {
  isStreaming: boolean;
  activeTurnId: string | null;
  completedTurnIds?: readonly string[];
}

interface QueuedPromptDelivery {
  disabled: boolean;
  onSend: (
    content: string,
    images?: SendAttachment[],
    options?: SendOptions,
  ) => boolean | void | Promise<boolean | void>;
  validate: (prompt: QueuedPromptContent) => string | null;
  onValidationError: (error: string) => void;
  onSendAttempt: () => void;
}

// Composer supplies draft content and UI feedback, not persistence or execution permission.
export function useQueuedPrompt(
  pendingQueueKey: string | null,
  { isStreaming, activeTurnId, completedTurnIds = EMPTY_COMPLETED_TURN_IDS }: QueuedPromptRun,
  { disabled, onSend, validate, onValidationError, onSendAttempt }: QueuedPromptDelivery,
) {
  const storageKey = queuedPromptsStorageKey(pendingQueueKey);
  const store = useMemo(() => queuedPromptStoreFor(storageKey), [storageKey]);
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const queuedPrompt = snapshot.prompt;
  const setQueuedPrompt = store.set;
  const interactionDisabled = disabled || snapshot.sending;
  const queuedPromptCounterRef = useRef(0);
  const previousQueueRunRef = useRef({ key: pendingQueueKey, isStreaming });

  useEffect(() => {
    if (!isStreaming || !activeTurnId) return;
    setQueuedPrompt((prompt) => (
      !prompt || prompt.autoPaused || prompt.autoAfterTurnId === activeTurnId
        ? prompt
        : { ...prompt, autoAfterTurnId: activeTurnId }
    ));
  }, [activeTurnId, isStreaming, pendingQueueKey, setQueuedPrompt]);

  // Prepare the complete message without publishing it, for validation or return to the editor.
  const collect = useCallback((content: QueuedPromptContent): QueuedPrompt => {
    queuedPromptCounterRef.current += 1;
    const prompt: QueuedPrompt = {
      id: `queued-prompt-${Date.now()}-${queuedPromptCounterRef.current}`,
      text: content.text.trim(),
      autoSendPageId: getQueuedPromptPageId(),
      images: content.images,
      ...(activeTurnId ? { autoAfterTurnId: activeTurnId } : {}),
      ...(content.quotedContext ? { quotedContext: content.quotedContext } : {}),
      sessionMentions: content.sessionMentions,
    };
    return queuedPrompt ? mergeQueuedPrompt(queuedPrompt, prompt) : prompt;
  }, [activeTurnId, queuedPrompt]);

  const enqueue = useCallback((prompt: QueuedPrompt): boolean => {
    const error = validate(prompt);
    if (error) {
      onValidationError(error);
      return false;
    }
    setQueuedPrompt(prompt);
    return true;
  }, [onValidationError, setQueuedPrompt, validate]);

  const clear = useCallback(() => {
    setQueuedPrompt(null);
  }, [setQueuedPrompt]);

  const pause = useCallback(() => {
    setQueuedPrompt((prompt) => prompt ? pauseQueuedPrompt(prompt) : null);
  }, [setQueuedPrompt]);

  const send = useCallback(
    (prompt: QueuedPrompt, extraOptions?: SendOptions) => {
      if (interactionDisabled) return;
      const error = validate(prompt);
      if (error) {
        setQueuedPrompt(pauseQueuedPrompt(prompt));
        onValidationError(error);
        return;
      }
      const text = prompt.text.trim();
      const queuedImages = queuedImagesToSendImages(prompt.images);
      const options: SendOptions | undefined = (
        extraOptions || prompt.quotedContext || prompt.sessionMentions?.length || isStreaming
      )
        ? {
            ...extraOptions,
            ...(prompt.quotedContext ? { quotedContext: prompt.quotedContext } : {}),
            ...(prompt.sessionMentions?.length ? { sessionMentions: prompt.sessionMentions } : {}),
            ...(isStreaming ? { continueActiveTurn: true } : {}),
          }
        : undefined;
      store.send(prompt, () => (
        options ? onSend(text, queuedImages, options)
          : queuedImages?.length ? onSend(text, queuedImages)
          : onSend(text)
      ));
      onSendAttempt();
    },
    [interactionDisabled, isStreaming, onSend, onSendAttempt, onValidationError, store, validate, setQueuedPrompt],
  );

  useEffect(() => {
    const previous = previousQueueRunRef.current;
    previousQueueRunRef.current = { key: pendingQueueKey, isStreaming };
    // Switching to an idle session is not completion of the previous session's run.
    if (previous.key !== pendingQueueKey) return;
    if (isStreaming || interactionDisabled || !queuedPrompt || !canAutoSendQueuedPrompt(queuedPrompt)) return;
    const waitingTurnCompleted = storageKey !== null && queuedPrompt.autoAfterTurnId !== undefined
      ? completedTurnIds.includes(queuedPrompt.autoAfterTurnId)
      : previous.isStreaming;
    if (!waitingTurnCompleted) return;
    send(queuedPrompt);
  }, [completedTurnIds, interactionDisabled, send, isStreaming, pendingQueueKey, queuedPrompt, storageKey]);

  return { snapshot, collect, enqueue, clear, pause, send };
}
