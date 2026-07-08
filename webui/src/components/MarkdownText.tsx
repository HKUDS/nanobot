import {
  Component,
  Suspense,
  lazy,
  memo,
  startTransition,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";
import { useStreamingNaturalPacing } from "@/lib/localPreferences";

interface MarkdownTextProps {
  children: string;
  className?: string;
  streaming?: boolean;
  onOpenFilePreview?: (path: string) => void;
}

const loadMarkdownRenderer = () => import("@/components/MarkdownTextRenderer");
const LazyMarkdownRenderer = lazy(loadMarkdownRenderer);

const MemoizedMarkdownRenderer = memo(function MemoizedMarkdownRenderer({
  source,
  className,
  highlightCode,
  onOpenFilePreview,
  streamRevealFrom,
  streamVisibleUntil,
  streamRevealKey,
}: {
  source: string;
  className?: string;
  highlightCode: boolean;
  onOpenFilePreview?: (path: string) => void;
  streamRevealFrom?: number;
  streamVisibleUntil?: number;
  streamRevealKey?: number;
}) {
  return (
    <LazyMarkdownRenderer
      className={className}
      highlightCode={highlightCode}
      onOpenFilePreview={onOpenFilePreview}
      streamRevealFrom={streamRevealFrom}
      streamVisibleUntil={streamVisibleUntil}
      streamRevealKey={streamRevealKey}
    >
      {source}
    </LazyMarkdownRenderer>
  );
});

const SHORT_STREAM_COMMIT_MS = 64;
const MEDIUM_STREAM_COMMIT_MS = 80;
const LONG_STREAM_COMMIT_MS = 96;
const STREAMING_HIGHLIGHT_CHAR_LIMIT = 16_000;
const LATIN_READING_CHARS_PER_SECOND = 30;
const CJK_READING_CHARS_PER_SECOND = 12;
const MIN_REVEAL_CHUNK_CHARS = 1;
const NORMAL_REVEAL_CHUNK_CHARS = 12;
const PRESSURED_REVEAL_CHUNK_CHARS = 18;
const MAX_REVEAL_CHUNK_CHARS = 24;
const MINOR_PUNCTUATION_PAUSE_MS = 45;
const MAJOR_PUNCTUATION_PAUSE_MS = 115;

class MarkdownRendererBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function preloadMarkdownText(): void {
  void loadMarkdownRenderer();
}

/**
 * Lightweight markdown renderer mirroring agent-chat-ui: GFM + math via
 * ``remark-math`` / ``rehype-katex``, and fenced code blocks delegated to
 * ``CodeBlock`` for copy-to-clipboard and syntax highlighting.
 */
export function MarkdownText({
  children,
  className,
  streaming = false,
  onOpenFilePreview,
}: MarkdownTextProps) {
  const streamingNaturalPacing = useStreamingNaturalPacing(streaming);
  const presentation = useStreamingMarkdownSource(
    children,
    streaming,
    streamingNaturalPacing,
  );
  const highlightCode = streaming
    ? presentation.source.length <= STREAMING_HIGHLIGHT_CHAR_LIMIT
    : presentation.source === children;

  useEffect(() => {
    if (streaming) preloadMarkdownText();
  }, [streaming]);

  const fallbackSource = streaming
    ? presentation.source.slice(0, presentation.visibleUntil)
    : presentation.source;
  const plainFallback = (
    <div
      className={cn(
        "whitespace-pre-wrap break-words leading-relaxed text-foreground/92",
        className,
      )}
    >
      {fallbackSource}
    </div>
  );

  return (
    <MarkdownRendererBoundary fallback={plainFallback}>
      <Suspense fallback={plainFallback}>
        <MemoizedMarkdownRenderer
          source={presentation.source}
          className={className}
          highlightCode={highlightCode}
          onOpenFilePreview={onOpenFilePreview}
          streamRevealFrom={streaming ? presentation.revealFrom : undefined}
          streamVisibleUntil={streaming ? presentation.visibleUntil : undefined}
          streamRevealKey={streaming ? presentation.revealKey : undefined}
        />
      </Suspense>
    </MarkdownRendererBoundary>
  );
}

interface StreamingPresentationState {
  source: string;
  visibleUntil: number;
  revealFrom: number;
  revealKey: number;
}

function useStreamingMarkdownSource(
  source: string,
  streaming: boolean,
  naturalPacing: boolean,
): StreamingPresentationState {
  const [rendered, setRendered] = useState<StreamingPresentationState>({
    source,
    visibleUntil: source.length,
    revealFrom: source.length,
    revealKey: 0,
  });
  const latestSourceRef = useRef(source);
  const presentationRef = useRef<StreamingPresentationState>({
    source,
    visibleUntil: source.length,
    revealFrom: source.length,
    revealKey: 0,
  });
  const frameRef = useRef<number | null>(null);
  const lastFrameAtRef = useRef<number | null>(null);
  const carryRef = useRef(0);
  const revealKeyRef = useRef(0);
  const punctuationPauseUntilRef = useRef(0);

  const clearPendingFrame = useCallback(() => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    lastFrameAtRef.current = null;
    carryRef.current = 0;
    punctuationPauseUntilRef.current = 0;
  }, []);

  const commitPresentation = useCallback((
    nextSource: string,
    nextVisibleUntil: number,
    nextRevealFrom: number,
    urgent: boolean,
  ) => {
    const previous = presentationRef.current;
    if (
      previous.source === nextSource
      && previous.visibleUntil === nextVisibleUntil
      && previous.revealFrom === nextRevealFrom
    ) {
      return;
    }
    revealKeyRef.current += 1;
    const state = {
      source: nextSource,
      visibleUntil: nextVisibleUntil,
      revealFrom: nextRevealFrom,
      revealKey: revealKeyRef.current,
    };
    presentationRef.current = state;
    if (urgent) {
      setRendered(state);
      return;
    }
    startTransition(() => setRendered(state));
  }, []);

  const stepPresentation = useCallback((timestamp: number) => {
    frameRef.current = null;
    const target = latestSourceRef.current;
    const previous = presentationRef.current;
    if (previous.visibleUntil >= target.length) {
      lastFrameAtRef.current = null;
      carryRef.current = 0;
      punctuationPauseUntilRef.current = 0;
      if (previous.source !== target) {
        commitPresentation(target, target.length, target.length, false);
      }
      return;
    }

    const frameMs = streamingCommitDelay(target.length);
    const lastFrameAt = lastFrameAtRef.current ?? timestamp - frameMs;
    const elapsed = Math.max(0, timestamp - lastFrameAt);
    if (elapsed < frameMs) {
      frameRef.current = window.requestAnimationFrame(stepPresentation);
      return;
    }

    if (timestamp < punctuationPauseUntilRef.current) {
      lastFrameAtRef.current = timestamp;
      frameRef.current = window.requestAnimationFrame(stepPresentation);
      return;
    }

    lastFrameAtRef.current = timestamp;
    const readingCharsPerSecond = estimateReadingCharsPerSecond(target, previous.visibleUntil);
    const backlog = target.length - previous.visibleUntil;
    const charsPerSecond = streamingRevealCharsPerSecond(backlog, readingCharsPerSecond);
    const rawAdvance = (charsPerSecond * elapsed) / 1_000 + carryRef.current;
    const advance = Math.floor(rawAdvance);
    if (advance < MIN_REVEAL_CHUNK_CHARS) {
      carryRef.current = rawAdvance;
      frameRef.current = window.requestAnimationFrame(stepPresentation);
      return;
    }

    carryRef.current = rawAdvance - advance;
    const cappedAdvance = Math.min(advance, streamingRevealChunkLimit(backlog));
    const nextVisibleUntil = advanceRevealOffset(target, previous.visibleUntil, cappedAdvance);
    const piece = target.slice(previous.visibleUntil, nextVisibleUntil);
    punctuationPauseUntilRef.current = nextPunctuationPauseUntil(piece, timestamp);

    commitPresentation(target, nextVisibleUntil, previous.visibleUntil, false);
    if (nextVisibleUntil < target.length) {
      frameRef.current = window.requestAnimationFrame(stepPresentation);
    }
  }, [commitPresentation]);

  const schedulePresentation = useCallback(() => {
    if (frameRef.current !== null) return;
    frameRef.current = window.requestAnimationFrame(stepPresentation);
  }, [stepPresentation]);

  latestSourceRef.current = source;

  useLayoutEffect(() => {
    latestSourceRef.current = source;
    if (!streaming) {
      clearPendingFrame();
      commitPresentation(source, source.length, source.length, true);
      return;
    }

    const previous = presentationRef.current;
    const isAppend = source.startsWith(previous.source);
    if (!isAppend || previous.visibleUntil > source.length) {
      clearPendingFrame();
      commitPresentation(source, source.length, source.length, true);
      return;
    }

    if (!naturalPacing) {
      clearPendingFrame();
      commitPresentation(source, source.length, previous.visibleUntil, false);
      return;
    }

    commitPresentation(source, previous.visibleUntil, previous.visibleUntil, false);
    schedulePresentation();
  }, [
    clearPendingFrame,
    commitPresentation,
    naturalPacing,
    schedulePresentation,
    source,
    streaming,
  ]);

  useEffect(() => {
    latestSourceRef.current = source;
    if (!streaming || !naturalPacing) return;
    schedulePresentation();
  }, [naturalPacing, schedulePresentation, source, streaming]);

  useEffect(() => clearPendingFrame, [clearPendingFrame]);

  return rendered;
}

function streamingCommitDelay(length: number): number {
  if (length > 24_000) return LONG_STREAM_COMMIT_MS;
  if (length > 8_000) return MEDIUM_STREAM_COMMIT_MS;
  return SHORT_STREAM_COMMIT_MS;
}

function streamingRevealCharsPerSecond(
  backlog: number,
  readingCharsPerSecond: number,
): number {
  return readingCharsPerSecond * streamingBacklogPressure(backlog);
}

function streamingBacklogPressure(backlog: number): number {
  if (backlog > 2_000) return 3.4;
  if (backlog > 900) return 2.8;
  if (backlog > 420) return 1.9;
  if (backlog > 160) return 1.35;
  return 1;
}

function streamingRevealChunkLimit(backlog: number): number {
  if (backlog > 500) return MAX_REVEAL_CHUNK_CHARS;
  if (backlog > 160) return PRESSURED_REVEAL_CHUNK_CHARS;
  return NORMAL_REVEAL_CHUNK_CHARS;
}

function nextPunctuationPauseUntil(piece: string, timestamp: number): number {
  const lastVisible = lastVisibleCharacter(piece);
  if (!lastVisible) return 0;
  if (/[。！？；!?;]/.test(lastVisible)) return timestamp + MAJOR_PUNCTUATION_PAUSE_MS;
  if (/[，、：,:]/.test(lastVisible)) return timestamp + MINOR_PUNCTUATION_PAUSE_MS;
  return 0;
}

function lastVisibleCharacter(value: string): string {
  for (let index = value.length - 1; index >= 0; index -= 1) {
    const character = value[index];
    if (!/\s/.test(character)) return character;
  }
  return "";
}

function estimateReadingCharsPerSecond(source: string, from: number): number {
  const sample = source.slice(from, Math.min(source.length, from + 400));
  if (!sample) return LATIN_READING_CHARS_PER_SECOND;
  let cjk = 0;
  let visible = 0;
  for (let index = 0; index < sample.length; index += 1) {
    const code = sample.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      index += 1;
      visible += 1;
      continue;
    }
    if (/\s/.test(sample[index])) continue;
    visible += 1;
    if (isCjkCodePoint(code)) cjk += 1;
  }
  if (visible === 0) return LATIN_READING_CHARS_PER_SECOND;
  const cjkRatio = cjk / visible;
  return Math.round(
    CJK_READING_CHARS_PER_SECOND * cjkRatio
      + LATIN_READING_CHARS_PER_SECOND * (1 - cjkRatio),
  );
}

function isCjkCodePoint(code: number): boolean {
  return (code >= 0x3400 && code <= 0x9fff)
    || (code >= 0xf900 && code <= 0xfaff)
    || (code >= 0x3040 && code <= 0x30ff)
    || (code >= 0xac00 && code <= 0xd7af);
}

function advanceRevealOffset(source: string, from: number, advance: number): number {
  const next = Math.min(source.length, from + advance);
  return alignRevealOffset(source, next);
}

function alignRevealOffset(source: string, offset: number): number {
  let next = Math.max(0, Math.min(source.length, offset));
  if (next <= 0 || next >= source.length) return next;
  const previousCode = source.charCodeAt(next - 1);
  const nextCode = source.charCodeAt(next);
  if (previousCode >= 0xd800 && previousCode <= 0xdbff) {
    next += 1;
  } else if (nextCode >= 0xdc00 && nextCode <= 0xdfff) {
    next += 1;
  }
  return Math.min(source.length, next);
}
