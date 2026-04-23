import { Suspense, lazy } from "react";

import { cn } from "@/lib/utils";

interface MarkdownTextProps {
  children: string;
  className?: string;
}

const loadMarkdownRenderer = () => import("@/components/MarkdownTextRenderer");
const LazyMarkdownRenderer = lazy(loadMarkdownRenderer);

export function preloadMarkdownText(): void {
  void loadMarkdownRenderer();
}

/**
 * Lightweight markdown renderer mirroring agent-chat-ui: GFM + math via
 * ``remark-math`` / ``rehype-katex``, and fenced code blocks delegated to
 * ``CodeBlock`` for copy-to-clipboard and syntax highlighting.
 */
export function MarkdownText({ children, className }: MarkdownTextProps) {
  return (
    <Suspense
      fallback={
        <div
          className={cn(
            "whitespace-pre-wrap break-words leading-relaxed text-foreground/92",
            className,
          )}
        >
          {children}
        </div>
      }
    >
      <LazyMarkdownRenderer className={className}>{children}</LazyMarkdownRenderer>
    </Suspense>
  );
}
