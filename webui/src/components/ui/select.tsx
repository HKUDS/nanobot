import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

import { floatingSurfaceElevationClassName, floatingItemClassName } from "@/components/ui/floating-surface";
import { useFloatingPortal } from "@/components/ui/floating-portal";
import { cn } from "@/lib/utils";

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger ref={ref} {...props}
    className={cn("flex h-9 items-center justify-between gap-2 rounded-control border border-input bg-background px-3 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 [&>span:first-child]:truncate", className)}>
    {children}
    <SelectPrimitive.Icon asChild><ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden /></SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = "SelectTrigger";

export function SelectContent({ children }: { children: React.ReactNode }) {
  const container = useFloatingPortal();
  return (
    <SelectPrimitive.Portal container={container ?? undefined}>
      <SelectPrimitive.Content position="item-aligned" className={cn("z-50 max-h-[min(24rem,calc(100dvh-2rem))] min-w-[10rem] overflow-hidden rounded-control border border-transparent", floatingSurfaceElevationClassName)}>
        <SelectPrimitive.ScrollUpButton className="flex h-6 items-center justify-center"><ChevronUp className="h-3.5 w-3.5" /></SelectPrimitive.ScrollUpButton>
        <SelectPrimitive.Viewport className="p-1">
          {children}
        </SelectPrimitive.Viewport>
        <SelectPrimitive.ScrollDownButton className="flex h-6 items-center justify-center"><ChevronDown className="h-3.5 w-3.5" /></SelectPrimitive.ScrollDownButton>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

export function SelectItem({ children, className, ...props }: React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>) {
  return (
    <SelectPrimitive.Item {...props} className={cn(floatingItemClassName, "h-9 py-0 pl-2 pr-8 data-[state=checked]:bg-muted data-[highlighted]:bg-muted data-[disabled]:opacity-50", className)}>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator className="absolute right-2 flex items-center"><Check className="h-3.5 w-3.5" aria-hidden /></SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  );
}
