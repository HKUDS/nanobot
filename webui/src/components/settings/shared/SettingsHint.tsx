import { useState, type ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export function SettingsHint({ children, description }: { children: ReactNode; description: string }) {
  const [open, setOpen] = useState(false);
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={(event) => { event.preventDefault(); setOpen(true); }}
            className="max-w-full cursor-help rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {children}
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-[min(22rem,calc(100vw-2rem))] whitespace-normal text-pretty leading-5">
          {description}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
