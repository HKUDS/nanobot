import {
  Suspense,
  lazy,
  memo,
  startTransition,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { cn } from "@/lib/utils";

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
}: {
  source: string;
  className?: string;
  highlightCode: boolean;
  onOpenFilePreview?: (path: string) => void;
}) {
  return (
    <LazyMarkdownRenderer
      className={className}
      highlightCode={highlightCode}
      onOpenFilePreview={onOpenFilePreview}
    >
      {source}
    </LazyMarkdownRenderer>
  );
});

const SHORT_STREAM_COMMIT_MS = 80;
const MEDIUM_STREAM_COMMIT_MS = 140;
const LONG_STREAM_COMMIT_MS = 220;
const STREAMING_HIGHLIGHT_CHAR_LIMIT = 16_000;

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
  const renderedSource = useStreamingMarkdownSource(children, streaming);
  const highlightCode = streaming
    ? renderedSource.length <= STREAMING_HIGHLIGHT_CHAR_LIMIT
    : renderedSource === children;

  useEffect(() => {
    if (streaming) preloadMarkdownText();
  }, [streaming]);

  return (
    <Suspense
      fallback={
        <div
          className={cn(
            "whitespace-pre-wrap break-words leading-relaxed text-foreground/92",
            className,
          )}
        >
          {renderedSource}
        </div>
      }
    >
      <MemoizedMarkdownRenderer
        source={renderedSource}
        className={className}
        highlightCode={highlightCode}
        onOpenFilePreview={onOpenFilePreview}
      />
    </Suspense>
  );
}

function useStreamingMarkdownSource(source: string, streaming: boolean): string {
  const [renderedSource, setRenderedSource] = useState(source);
  const latestSourceRef = useRef(source);
  const renderedSourceRef = useRef(source);
  const timerRef = useRef<number | null>(null);

  const clearPendingCommit = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const commitSource = useCallback((next: string, urgent: boolean) => {
    if (renderedSourceRef.current === next) return;
    renderedSourceRef.current = next;
    if (urgent) {
      setRenderedSource(next);
      return;
    }
    startTransition(() => setRenderedSource(next));
  }, []);

  const scheduleCommit = useCallback(() => {
    if (timerRef.current !== null) return;
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      commitSource(latestSourceRef.current, false);
    }, streamingCommitDelay(latestSourceRef.current.length));
  }, [commitSource]);

  latestSourceRef.current = source;

  useLayoutEffect(() => {
    latestSourceRef.current = source;
    if (!streaming) {
      clearPendingCommit();
      commitSource(source, true);
    }
  }, [clearPendingCommit, commitSource, source, streaming]);

  useEffect(() => {
    latestSourceRef.current = source;
    if (!streaming) return;
    scheduleCommit();
  }, [scheduleCommit, source, streaming]);

  useEffect(() => clearPendingCommit, [clearPendingCommit]);

  return renderedSource;
}

function streamingCommitDelay(length: number): number {
  if (length > 24_000) return LONG_STREAM_COMMIT_MS;
  if (length > 8_000) return MEDIUM_STREAM_COMMIT_MS;
  return SHORT_STREAM_COMMIT_MS;
}
