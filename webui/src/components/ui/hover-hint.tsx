import * as React from "react";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip-primitives";
import { cn } from "@/lib/utils";

export function HoverHint({ content, children, enabled = true, side = "top", align = "center", sideOffset, contentClassName }: {
  content: React.ReactNode;
  children: React.ReactElement;
  enabled?: boolean;
  side?: React.ComponentPropsWithoutRef<typeof TooltipContent>["side"];
  align?: React.ComponentPropsWithoutRef<typeof TooltipContent>["align"];
  sideOffset?: number;
  contentClassName?: string;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <TooltipProvider>
      <Tooltip open={enabled && open} onOpenChange={(next) => setOpen(enabled && next)}>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent side={side} align={align} sideOffset={sideOffset}
          className={cn("max-w-[min(28rem,calc(100vw-2rem))] whitespace-pre-wrap break-words", contentClassName)}>
          {content}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

