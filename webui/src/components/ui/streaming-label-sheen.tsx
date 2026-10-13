import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** L→R sheen on the glyphs themselves; inactive labels stay solid muted text. */
export function StreamingLabelSheen({
  children,
  active,
  className,
}: {
  children: ReactNode;
  active: boolean;
  className?: string;
}) {
  const sheenText =
    typeof children === "string" || typeof children === "number"
      ? String(children)
      : undefined;
  return (
    <span className={cn("block min-w-0 overflow-hidden py-px", className)}>
      <span
        data-sheen-text={active ? sheenText : undefined}
        className={cn(
          "block w-fit max-w-full truncate pr-0.5 font-medium leading-normal",
          active ? "streaming-text-sheen after:pr-0.5" : "text-muted-foreground",
        )}
      >
        {children}
      </span>
    </span>
  );
}
