import { useEffect, useRef } from "react";
import "./thread-welcome-mark.css";

export function ThreadWelcomeMark() {
  const markRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mark = markRef.current;
    if (!mark) return;

    const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
    let currentX = 0;
    let currentY = 0;
    let targetX = 0;
    let targetY = 0;
    let frame = 0;
    let lastFrame: number | null = null;
    let initialized = false;

    const renderPosition = () => {
      mark.style.setProperty("--mark-x", `${currentX}px`);
      mark.style.setProperty("--mark-y", `${currentY}px`);
    };

    const followPointer = (timestamp: number) => {
      const elapsed = lastFrame === null ? 0 : timestamp - lastFrame;
      lastFrame = timestamp;
      const step = 1 - Math.exp(-elapsed / 165);
      currentX += (targetX - currentX) * step;
      currentY += (targetY - currentY) * step;
      if (Math.hypot(targetX - currentX, targetY - currentY) < 0.3) {
        currentX = targetX;
        currentY = targetY;
        frame = 0;
        lastFrame = null;
      } else {
        frame = window.requestAnimationFrame(followPointer);
      }
      renderPosition();
    };

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      const bounds = mark.getBoundingClientRect();
      targetX = event.clientX - bounds.left;
      targetY = event.clientY - bounds.top;
      mark.style.setProperty("--mark-active", "1");
      if (!initialized || motionPreference.matches) {
        if (frame) window.cancelAnimationFrame(frame);
        frame = 0;
        lastFrame = null;
        currentX = targetX;
        currentY = targetY;
        initialized = true;
        renderPosition();
      } else if (!frame) {
        frame = window.requestAnimationFrame(followPointer);
      }
    };

    const hideFocus = () => {
      mark.style.setProperty("--mark-active", "0");
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
      lastFrame = null;
      initialized = false;
    };
    const onPointerOut = (event: PointerEvent) => {
      if (!event.relatedTarget) hideFocus();
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerout", onPointerOut);
    window.addEventListener("blur", hideFocus);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerout", onPointerOut);
      window.removeEventListener("blur", hideFocus);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div ref={markRef} aria-hidden="true" data-testid="thread-welcome-mark" className="thread-welcome-mark">
      <div className="thread-welcome-mark__fill" />
      <div className="thread-welcome-mark__focus" />
    </div>
  );
}
