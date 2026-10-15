import * as React from "react";

import { HoverHint } from "@/components/ui/hover-hint";
import { cn } from "@/lib/utils";

export function TruncatedTextTooltip({ text, className, ...props }: {
  text: string;
} & Omit<React.ComponentPropsWithoutRef<"span">, "children" | "title">) {
  const ref = React.useRef<HTMLSpanElement>(null);
  const [truncated, setTruncated] = React.useState(false);

  React.useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setTruncated(element.scrollWidth > element.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    let mounted = true;
    void document.fonts.ready.then(() => { if (mounted) measure(); });
    return () => { mounted = false; observer.disconnect(); };
  }, [text]);

  return (
    <HoverHint content={text} enabled={truncated}>
      <span {...props} ref={ref} className={cn("min-w-0 truncate", className)}>{text}</span>
    </HoverHint>
  );
}

