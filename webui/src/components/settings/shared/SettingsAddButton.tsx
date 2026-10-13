import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Plus } from "lucide-react";

import { cn } from "@/lib/utils";

export const SettingsAddButton = forwardRef<HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { trailing?: ReactNode }
>(({ children, trailing, className, type = "button", ...props }, ref) => (
  <button {...props} ref={ref} type={type}
    className={cn("settings-list-row flex w-full items-center gap-3 py-2.5 text-left transition-colors settings-hover disabled:cursor-not-allowed disabled:opacity-50", className)}>
    <span className="flex min-w-0 flex-1 items-center gap-3">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[9px] bg-muted text-muted-foreground">
        <Plus className="h-5 w-5" aria-hidden />
      </span>
      <span className="truncate text-[14px] font-medium text-foreground">{children}</span>
    </span>
    {trailing}
  </button>
));
SettingsAddButton.displayName = "SettingsAddButton";
