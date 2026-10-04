import { useLayoutEffect } from "react";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { isNativeRuntime } from "@/lib/runtime";

/** One viewport owner for navigation, workbench composers and ordinary threads. */
export function useAppViewport() {
  const touch = useMediaQuery("(any-pointer: coarse)");
  useLayoutEffect(() => {
    const viewport = window.visualViewport;
    const root = document.getElementById("root");
    if (!touch || !viewport || !root || isNativeRuntime()) return;

    const update = () => {
      // Pinch zoom pans the existing layout; it must not reflow it or chase the
      // user's magnified viewport. Resume fitting when the scale returns to 1.
      if (viewport.scale !== 1) return;
      root.style.setProperty("--app-viewport-height", `${viewport.height}px`);
      // WebKit can report a negative offset after rotating a focused PWA.
      // Do not move the navigation above the top edge with that overscroll.
      root.style.setProperty("--app-viewport-top", `${Math.max(0, viewport.offsetTop)}px`);
      root.classList.add("visual-viewport");
      // Only the keyboard's shortest layouts need a scrollable composer.
      // Normal layouts must let the command and mention palettes overflow.
      root.classList.toggle("short-visual-viewport", viewport.height < 240);
    };
    update();
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    return () => {
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
      root.classList.remove("visual-viewport");
      root.classList.remove("short-visual-viewport");
      root.style.removeProperty("--app-viewport-height");
      root.style.removeProperty("--app-viewport-top");
    };
  }, [touch]);
}
