import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function SkeletonStatus({ label, className, children }: {
  label: string;
  className: string;
  children: ReactNode;
}) {
  return (
    <div role="status" aria-label={label} aria-busy="true">
      <span className="sr-only">{label}</span>
      <div aria-hidden className={cn("animate-pulse motion-reduce:animate-none", className)}>
        {children}
      </div>
    </div>
  );
}
