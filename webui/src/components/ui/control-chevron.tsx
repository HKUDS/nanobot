import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

export function ControlChevron({ className }: { className?: string }) {
  return (
    <ChevronDown
      // Keep the horizontal viewBox around the artwork, including its stroke.
      viewBox="5 0 14 24"
      width={14}
      height={24}
      className={cn("h-3.5 w-auto shrink-0 text-muted-foreground", className)}
      aria-hidden
    />
  );
}
