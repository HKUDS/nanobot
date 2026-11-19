import { useRef, type KeyboardEvent, type PointerEvent } from "react";

/** Return Escape to the control that opening an overlay interrupted. */
export function useOverlayEscapeFocus() {
  const opener = useRef<HTMLElement | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const escaped = useRef(false);
  return {
    triggerProps: {
      onPointerDownCapture: (event: PointerEvent<HTMLElement>) => {
        if (event.button !== 0) return;
        if (!escaped.current) opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        escaped.current = false;
        trigger.current = event.currentTarget;
      },
      onKeyDownCapture: (event: KeyboardEvent<HTMLElement>) => {
        if (event.key === "Enter" || event.key === " ") {
          escaped.current = false;
          trigger.current = event.currentTarget;
          opener.current = event.currentTarget;
        }
      },
    },
    contentProps: {
      onEscapeKeyDown: () => { escaped.current = true; },
      onCloseAutoFocus: (event: Event) => {
        const target = escaped.current ? opener.current : null;
        opener.current = null;
        escaped.current = false;
        if (!event.defaultPrevented && target?.isConnected && target !== document.body) {
          event.preventDefault();
          const active = document.activeElement;
          if (active === document.body || active === trigger.current || (event.target instanceof HTMLElement && event.target.contains(active))) {
            target.focus({ preventScroll: true });
          }
        }
      },
    },
  };
}
