import { useState, type ReactNode } from "react";
import { FileText, ImageIcon, Video } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { UIMediaKind } from "@/lib/types";
import { cn } from "@/lib/utils";

export const attachmentCardActionClassName = "absolute right-0 top-0 grid h-11 w-11 place-items-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring";

/** The card owns only its information surface; callers own removal, download, and status. */
export function AttachmentCard({ name, description, children, action, invalid = false }: {
  name: string;
  description?: string;
  children: ReactNode;
  action?: ReactNode;
  invalid?: boolean;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [hintOpen, setHintOpen] = useState(false);
  const changeDetailsOpen = (open: boolean) => { setDetailsOpen(open); setHintOpen(false); };
  const details = <>
    <span className="block font-medium">{name}</span>
    {description ? <span className="block text-muted-foreground">{description}</span> : null}
  </>;

  return <span className={cn(
    "relative block h-24 w-24 max-w-full shrink-0 rounded-control border transition-colors motion-reduce:transition-none",
    invalid ? "border-destructive/40 bg-destructive/5 text-destructive" : "border-border/70 bg-muted/35",
  )}>
    <TooltipProvider>
      <Tooltip open={hintOpen && !detailsOpen} onOpenChange={setHintOpen}>
        <Popover open={detailsOpen} onOpenChange={changeDetailsOpen}>
          <PopoverTrigger asChild>
            <TooltipTrigger asChild>
              <button type="button" aria-label={name} aria-description={description}
                onKeyDown={(event) => {
                  // The trigger retains focus while details are open, including during the layer handoff.
                  if (event.key === "Escape" && detailsOpen) {
                    event.preventDefault();
                    event.stopPropagation();
                    changeDetailsOpen(false);
                  }
                }}
                className="absolute inset-0 overflow-hidden rounded-[inherit] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                {children}
              </button>
            </TooltipTrigger>
          </PopoverTrigger>
          <PopoverContent side="top" aria-label={name}
            onOpenAutoFocus={(event) => event.preventDefault()}
            className="w-max max-w-[min(20rem,calc(100vw-2rem))] break-words px-3 py-1.5 text-caption">
            {details}
          </PopoverContent>
        </Popover>
        <TooltipContent side="top" className="max-w-[min(20rem,calc(100vw-2rem))] break-words">{details}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
    {action}
  </span>;
}

export function AttachmentTypeFace({ name, kind = "file" }: { name: string; kind?: UIMediaKind }) {
  const { t } = useTranslation();
  const type = name.match(/\.(tar\.(?:gz|bz2|xz)|[a-z0-9]{1,12})$/i)?.[1].toUpperCase()
    || t(kind === "image" ? "message.imageAttachment" : kind === "video" ? "message.videoAttachment" : "message.fileAttachment");
  const Icon = kind === "image" ? ImageIcon : kind === "video" ? Video : FileText;
  return <span className="flex h-full w-full flex-col items-center justify-center gap-2" aria-hidden>
    <Icon className="h-7 w-7 text-muted-foreground" strokeWidth={1.25} />
    <span className="max-w-full truncate px-2 text-[10px] font-semibold tracking-wide text-muted-foreground">{type}</span>
  </span>;
}
