import { useEffect, useId, useRef, useState, type KeyboardEventHandler, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Keep the content mounted so both directions animate and form drafts survive closing. */
export function DisclosureContent({
  open, children, id, className, onKeyDown, onExitComplete,
}: {
  open: boolean;
  children: ReactNode;
  id?: string;
  className?: string;
  onKeyDown?: KeyboardEventHandler<HTMLDivElement>;
  onExitComplete?: () => void;
}) {
  const node = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open || !onExitComplete) return;
    // Read the actual CSS transitions, including a reversal in progress. With
    // reduced motion (or no transition), there is nothing to wait for.
    const animations = node.current?.getAnimations?.() ?? [];
    if (!animations.length) {
      onExitComplete();
      return;
    }
    let cancelled = false;
    void Promise.allSettled(animations.map((animation) => animation.finished)).then(() => {
      if (!cancelled) onExitComplete();
    });
    return () => { cancelled = true; };
  }, [open, onExitComplete]);
  return (
    <div
      ref={node}
      id={id}
      className="inline-disclosure"
      data-state={open ? "open" : "closed"}
      aria-hidden={open ? undefined : true}
      onKeyDown={onKeyDown}
      {...(!open ? { inert: "" } : {})}
    >
      <div className="inline-disclosure-clip">
        <div className={cn("inline-disclosure-content", className)}>{children}</div>
      </div>
    </div>
  );
}

export function Disclosure({
  summary, children, className, summaryClassName, contentClassName,
}: {
  summary: ReactNode;
  children: ReactNode;
  className?: string;
  summaryClassName?: string;
  contentClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={className}>
      <button
        type="button"
        className={cn("group/disclosure w-full select-none text-start", summaryClassName)}
        data-state={open ? "open" : "closed"}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
      >
        {summary}
      </button>
      <DisclosureContent id={id} open={open} className={contentClassName}>
        {children}
      </DisclosureContent>
    </div>
  );
}
