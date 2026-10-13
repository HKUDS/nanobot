import { useRef, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";

export const SIDEBAR_MIN_WIDTH = 220;
export const SIDEBAR_MAX_WIDTH = 480;

interface SidebarResizeHandleProps {
  width: number;
  open: boolean;
  onResize: (width: number, open: boolean) => void;
  onDraggingChange: (dragging: boolean) => void;
}

export function SidebarResizeHandle({ width, open, onResize, onDraggingChange }: SidebarResizeHandleProps) {
  const { t } = useTranslation();
  const drag = useRef<{ x: number; width: number; open: boolean } | null>(null);
  const finish = () => {
    drag.current = null;
    onDraggingChange(false);
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (!start) return;
    const next = start.width + event.clientX - start.x;
    const expanded = start.open ? next >= 160 : next >= 200;
    start.open = expanded;
    onResize(Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, next)), expanded);
  };

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-label={t("sidebar.resize")}
      aria-orientation="vertical"
      aria-controls="main-sidebar"
      aria-valuemin={56}
      aria-valuemax={SIDEBAR_MAX_WIDTH}
      aria-valuenow={open ? width : 56}
      className="host-no-drag absolute inset-y-0 right-0 z-30 w-3 cursor-grab active:cursor-grabbing touch-none select-none outline-none after:absolute after:top-1/2 after:right-1 after:h-12 after:w-1 after:-translate-y-1/2 after:rounded-full after:bg-transparent hover:after:bg-orange-500/70 active:after:bg-orange-500 focus-visible:after:bg-orange-500"
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { x: event.clientX, width: open ? width : 56, open };
        onDraggingChange(true);
      }}
      onPointerMove={move}
      onPointerUp={(event) => {
        if (!drag.current) return;
        move(event);
        finish();
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={finish}
      onLostPointerCapture={finish}
      onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End", "Enter"].includes(event.key)) return;
        event.preventDefault();
        if (event.key === "Home") onResize(width, false);
        else if (event.key === "End") onResize(SIDEBAR_MAX_WIDTH, true);
        else if (event.key === "Enter") onResize(width, !open);
        else if (event.key === "ArrowLeft") onResize(Math.max(SIDEBAR_MIN_WIDTH, width - 32), open && width > SIDEBAR_MIN_WIDTH);
        else onResize(open ? Math.min(SIDEBAR_MAX_WIDTH, width + 32) : width, true);
      }}
    />
  );
}
