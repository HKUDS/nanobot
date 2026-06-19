import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface ActivityGroupProps {
  title: string;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
}

export function ActivityGroup({ title, icon: Icon, children, className }: ActivityGroupProps) {
  return (
    <section
      className={cn(
        "min-w-0 py-1 motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1 motion-safe:duration-200",
        className,
      )}
    >
      <div className="mb-1 flex min-w-0 items-center gap-1.5 pl-0.5 text-[12px] font-medium text-muted-foreground/70">
        {Icon ? <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden /> : null}
        <span className="min-w-0 truncate">{title}</span>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}
