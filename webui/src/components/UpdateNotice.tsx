import { Download } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { UpdateMethod } from "@/lib/api";

export function UpdateNotice({ version, collapsed = false, onOpen, onDismiss, onRequestUpdate, installationMethod }: {
  version: string;
  collapsed?: boolean;
  onOpen: () => void;
  onDismiss: () => void;
  /** Opens the host's update confirmation, never installs from the entry itself. */
  onRequestUpdate?: () => void;
  installationMethod?: UpdateMethod | null;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const methodLabel = installationMethod && installationMethod !== "managed"
    ? t("updates.guide.entry", { method: t(`updates.guide.methods.${installationMethod}`) }) : null;
  const label = [t("settings.about.updateAvailable", { version }), methodLabel].filter(Boolean).join(" · ");
  const button = <Button type="button" variant="ghost" aria-label={label} onClick={onRequestUpdate}
    className={cn(
      "touch-target h-8 min-w-0 gap-2 rounded-control text-blue-600 shadow-none hover:bg-blue-500/[0.08] data-[state=open]:bg-blue-500/[0.08] focus-visible:ring-blue-500 dark:text-blue-400 dark:hover:bg-blue-400/10 dark:data-[state=open]:bg-blue-400/10",
      collapsed ? "w-8 p-0" : "w-full justify-start px-2 text-[13px] font-medium",
    )}>
    <Download className="h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden />
    {!collapsed && <span className="truncate">{methodLabel ?? t("settings.about.updateNotice")}</span>}
  </Button>;

  return <div className={cn("flex shrink-0 items-center", collapsed ? "w-14 justify-center pb-1" : "px-2.5")}>
    {onRequestUpdate ? <TooltipProvider><Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip></TooltipProvider> : <Popover open={open} onOpenChange={setOpen}>
      {collapsed ? <TooltipProvider><Tooltip>
        <TooltipTrigger asChild><PopoverTrigger asChild>{button}</PopoverTrigger></TooltipTrigger>
        {!open && <TooltipContent side="right">{label}</TooltipContent>}
      </Tooltip></TooltipProvider> : <PopoverTrigger asChild>{button}</PopoverTrigger>}
      <PopoverContent side="top" align="start" sideOffset={8} collisionPadding={12}
        aria-labelledby={titleId} className="w-64 max-w-[calc(100vw-1.5rem)] p-3.5">
        <h2 id={titleId} className="text-[13px] font-medium">{label}</h2>
        <div className="mt-3 flex flex-wrap items-center justify-end gap-1.5">
          <Button type="button" variant="ghost" size="sm" className="touch-target h-8 px-2.5 text-xs text-muted-foreground"
            onClick={() => { setOpen(false); onDismiss(); }}>{t("settings.about.dismissUpdate")}</Button>
          <Button type="button" size="sm" variant="accent"
            className="touch-target h-8 px-2.5 text-xs"
            onClick={() => { setOpen(false); onOpen(); }}>{t("settings.about.viewUpdateDetails")}</Button>
        </div>
      </PopoverContent>
    </Popover>}
  </div>;
}
