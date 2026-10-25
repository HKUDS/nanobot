import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { floatingSurfaceElevationClassName } from "@/components/ui/floating-surface";
import { cn } from "@/lib/utils";
import { useHasTooltipRegion, useTooltipRegion, useTooltipRegionDismiss } from "@/components/ui/tooltip-region";

const HOVER_DELAY = 500;

function TooltipProvider(props: Omit<React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Provider>, "delayDuration" | "skipDelayDuration">) {
  return <TooltipPrimitive.Provider {...props} delayDuration={HOVER_DELAY} skipDelayDuration={0} />;
}
const TooltipContext = React.createContext<{
  triggerRef: React.MutableRefObject<HTMLButtonElement | null>;
  dismiss: () => void;
  resume: (pointer: boolean) => void;
  cancelPending: () => void;
} | null>(null);

function Tooltip({ open: controlledOpen, defaultOpen = false, onOpenChange, ...props }: React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Root>) {
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = React.useState(defaultOpen);
  const regional = useHasTooltipRegion();
  const dismissed = React.useRef(false);
  const pointerIntent = React.useRef(false);
  const pending = React.useRef<ReturnType<typeof setTimeout>>();
  const onChangeRef = React.useRef(onOpenChange);
  React.useLayoutEffect(() => { onChangeRef.current = onOpenChange; }, [onOpenChange]);
  const cancelPending = React.useCallback(() => { clearTimeout(pending.current); }, []);
  React.useEffect(() => cancelPending, [cancelPending]);
  const commitOpen = React.useCallback((next: boolean) => {
    setOpen(next);
    onChangeRef.current?.(next);
  }, []);
  const changeOpen = React.useCallback((next: boolean) => {
    cancelPending();
    if (next && dismissed.current) return;
    // Controlled Radix closes do not reset its provider's skip-delay state.
    // Regional hints own the pointer delay so editing can cancel it reliably.
    if (regional && next && pointerIntent.current) {
      pending.current = setTimeout(() => commitOpen(true), HOVER_DELAY);
    } else commitOpen(next);
  }, [cancelPending, commitOpen, regional]);
  const dismiss = React.useCallback(() => {
    dismissed.current = true;
    cancelPending();
    commitOpen(false);
  }, [cancelPending, commitOpen]);
  const resume = React.useCallback((pointer: boolean) => {
    dismissed.current = false;
    pointerIntent.current = pointer;
    if (!pointer) cancelPending();
  }, [cancelPending]);
  useTooltipRegionDismiss(triggerRef, dismiss);
  const context = React.useMemo(() => ({ triggerRef, dismiss, resume, cancelPending }), [dismiss, resume, cancelPending]);
  return <TooltipContext.Provider value={context}>
    <TooltipPrimitive.Root {...props} delayDuration={regional ? 0 : props.delayDuration}
      open={controlledOpen ?? open} onOpenChange={changeOpen} />
  </TooltipContext.Provider>;
}

const TooltipTrigger = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Trigger>
>((props, ref) => {
  const context = React.useContext(TooltipContext);
  const triggerRef = context?.triggerRef;
  const attach = React.useCallback((element: HTMLButtonElement | null) => {
    if (triggerRef) triggerRef.current = element;
    if (typeof ref === "function") ref(element);
    else if (ref) ref.current = element;
  }, [triggerRef, ref]);
  return <TooltipPrimitive.Trigger {...props} ref={attach}
    onPointerEnter={event => { props.onPointerEnter?.(event); if (!event.defaultPrevented) context?.resume(true); }}
    onPointerLeave={event => { props.onPointerLeave?.(event); context?.cancelPending(); }}
    onFocus={event => { props.onFocus?.(event); if (!event.defaultPrevented) context?.resume(false); }} />;
});
TooltipTrigger.displayName = TooltipPrimitive.Trigger.displayName;

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, style, ...props }, ref) => {
  const context = React.useContext(TooltipContext);
  const [content, setContent] = React.useState<HTMLDivElement | null>(null);
  const placement = useTooltipRegion(context?.triggerRef, content, context?.dismiss);
  const attach = React.useCallback((element: HTMLDivElement | null) => {
    setContent(element);
    if (typeof ref === "function") ref(element);
    else if (ref) ref.current = element;
  }, [ref]);
  return <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={attach}
      sideOffset={sideOffset}
      className={cn(
        floatingSurfaceElevationClassName,
        "z-50 overflow-hidden rounded-control px-3 py-1.5 text-caption animate-in fade-in-0 zoom-in-95",
        placement && "whitespace-pre-wrap break-words",
        className,
      )}
      {...props}
      {...placement}
      style={{ ...style, ...placement?.style }}
    />
  </TooltipPrimitive.Portal>;
});
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger };
