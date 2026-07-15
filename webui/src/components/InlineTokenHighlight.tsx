import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const INLINE_TOKEN_HIGHLIGHT_COLOR = "hsl(var(--inline-token-highlight))";

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
        "relative inline transition-[color,text-shadow] duration-150",
        className,
      )}
      style={{
        color,
        textShadow: `0 0 10px ${alphaColor(color, 24)}`,
      }}
    >
      {children}
    </span>
  );
}

function alphaColor(color: string, percent: number): string {
  if (/^#[0-9a-f]{6}$/i.test(color)) {
    const alpha = Math.round((percent / 100) * 255)
      .toString(16)
      .padStart(2, "0");
    return `${color}${alpha}`;
  }
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`;
}
