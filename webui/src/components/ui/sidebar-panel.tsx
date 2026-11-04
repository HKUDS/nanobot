import { forwardRef, useCallback, useLayoutEffect, useRef, useState, type CSSProperties, type HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

interface SidebarPanelProps extends HTMLAttributes<HTMLElement> {
  width: number;
  isClosing?: boolean;
  floating?: boolean;
  contentClassName?: string;
}

/** Shared nonmodal side slot. Contents keep their final width while the slot opens. */
export const SidebarPanel = forwardRef<HTMLElement, SidebarPanelProps>(function SidebarPanel({
  width, isClosing = false, floating = false, contentClassName, className, style, children, ...props
}, forwardedRef) {
  const panel = useRef<HTMLElement | null>(null);
  const [entered, setEntered] = useState(false);
  const setPanel = useCallback((node: HTMLElement | null) => {
    panel.current = node;
    if (typeof forwardedRef === "function") forwardedRef(node);
    else if (forwardedRef) forwardedRef.current = node;
  }, [forwardedRef]);
  useLayoutEffect(() => {
    // Commit the outgoing slot width before transitioning to the replacement width.
    panel.current?.getBoundingClientRect();
    let frame = requestAnimationFrame(() => { frame = requestAnimationFrame(() => setEntered(true)); });
    return () => cancelAnimationFrame(frame);
  }, []);
  return <aside {...props} ref={setPanel}
    style={{
      "--file-preview-width": `${width}px`,
      "--file-preview-slot-width": isClosing ? "0px" : !entered ? "var(--sidebar-enter-width, 0px)" : `${width}px`,
      "--file-preview-mobile-width": isClosing ? "0px" : !entered ? "var(--sidebar-enter-mobile-width, 0px)" : "100%",
      ...style,
    } as CSSProperties}
    className={cn("file-preview-pane z-30 min-h-0 w-[var(--file-preview-mobile-width)] overflow-hidden duration-300 ease-[cubic-bezier(0.2,0,0,1)] motion-reduce:transition-none",
      entered ? "transition-[width]" : "transition-none",
      floating ? "fixed inset-y-2 right-2 max-w-[420px]" : "absolute inset-y-0 right-0", isClosing && "pointer-events-none", className)}>
    <div className={cn("file-preview-content absolute inset-y-2 right-2 flex min-h-0 w-[calc(100cqw-1rem)] flex-col pb-[env(safe-area-inset-bottom)] transition-[opacity,transform] duration-200 ease-out motion-reduce:transition-none",
      floating && "w-[calc(min(420px,100vw)-1rem)]",
      !entered || isClosing ? "translate-x-2 opacity-0" : "translate-x-0 opacity-100", contentClassName)}>
      {children}
    </div>
  </aside>;
});
