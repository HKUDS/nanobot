import {
  Component,
  Suspense,
  lazy,
  memo,
  useEffect,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";
import type { SessionHandle } from "@/lib/types";

interface MarkdownTextProps {
  children: string;
  className?: string;
  streaming?: boolean;
  preserveStreamingLayout?: boolean;
  onOpenFilePreview?: (path: string) => void;
  sessionHandles?: SessionHandle[];
}

const loadMarkdownRenderer = () => import("@/components/MarkdownTextRenderer");
const LazyMarkdownRenderer = lazy(loadMarkdownRenderer);

const MemoizedMarkdownRenderer = memo(function MemoizedMarkdownRenderer({
  source,
  className,
  highlightCode,
  streaming,
  onOpenFilePreview,
  sessionHandles,
}: {
  source: string;
  className?: string;
  highlightCode: boolean;
  streaming: boolean;
  onOpenFilePreview?: (path: string) => void;
  sessionHandles?: SessionHandle[];
}) {
  return (
    <LazyMarkdownRenderer
      className={className}
      highlightCode={highlightCode}
      streaming={streaming}
      onOpenFilePreview={onOpenFilePreview}
      sessionHandles={sessionHandles}
    >
      {source}
    </LazyMarkdownRenderer>
  );
});

class MarkdownRendererBoundary extends Component<
  { children: ReactNode; fallback: ReactNode; resetKey: string },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(previous: Readonly<{ resetKey: string }>) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function preloadMarkdownText(): Promise<void> {
  return loadMarkdownRenderer().then(() => undefined);
}

/** Lazy boundary for the heavier GFM, math, and code renderer. */
export function MarkdownText({
  children,
  className,
  streaming = false,
  preserveStreamingLayout = false,
  onOpenFilePreview,
  sessionHandles,
}: MarkdownTextProps) {
  const renderedSource = children;
  const renderPhase = streaming ? "streaming" : "complete";
  const highlightCode = !streaming;
  const renderWithStreamingLayout = streaming || preserveStreamingLayout;

  useEffect(() => {
    if (streaming) void preloadMarkdownText();
  }, [streaming]);

  const plainFallback = (
    <div
      className={cn(
        "whitespace-pre-wrap break-words leading-relaxed text-foreground/92",
        streaming && "streaming-text-fallback",
        className,
      )}
    >
      {renderedSource}
    </div>
  );

  return (
    <MarkdownRendererBoundary resetKey={renderPhase} fallback={plainFallback}>
      <Suspense fallback={plainFallback}>
        <MemoizedMarkdownRenderer
          source={renderedSource}
          className={className}
          highlightCode={highlightCode}
          streaming={renderWithStreamingLayout}
          onOpenFilePreview={onOpenFilePreview}
          sessionHandles={sessionHandles}
        />
      </Suspense>
    </MarkdownRendererBoundary>
  );
}
