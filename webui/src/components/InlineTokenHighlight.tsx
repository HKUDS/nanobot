import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const INLINE_TOKEN_HIGHLIGHT_COLOR = "var(--inline-token-highlight)";

export function InlineTokenHighlight({
  children,
  className,
  color,
  testId,
  title,
}: {
  children: ReactNode;
  className?: string;
  color: string;
  testId?: string;
  title?: string;
}) {
  return (
    <span
      data-testid={testId}
      title={title}
      className={cn(
        "relative inline font-[550] transition-colors duration-150",
        className,
      )}
      style={{ color }}
    >
      {children}
    </span>
  );
}
