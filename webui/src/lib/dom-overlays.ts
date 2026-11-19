import { useCallback, useRef, type ForwardedRef, type RefCallback } from "react";

type OverlayKind = "dialog" | "overlay";
const surfaces = new Map<HTMLElement, OverlayKind>();

// Track the content node's presence, not the owner's open prop: Radix can keep
// closed content mounted through its exit animation.
export function useOverlaySurfaceRef<T extends HTMLElement>(
  kind: OverlayKind,
  forwardedRef?: ForwardedRef<T>,
): RefCallback<T> {
  const current = useRef<T | null>(null);
  return useCallback((node) => {
    if (current.current) surfaces.delete(current.current);
    current.current = node;
    if (node) surfaces.set(node, kind);

    if (typeof forwardedRef === "function") forwardedRef(node);
    else if (forwardedRef) forwardedRef.current = node;
  }, [kind, forwardedRef]);
}

function hasDialogSurface(includeClosed: boolean): boolean {
  for (const [node, kind] of surfaces) {
    if (kind === "dialog" && node.isConnected && (includeClosed || node.dataset.state !== "closed")) return true;
  }
  return false;
}

export function hasAnyDialogMounted(): boolean {
  return hasDialogSurface(true);
}

export function hasOpenDialogSurface(): boolean {
  return hasDialogSurface(false);
}

export function hasAnyOverlayMounted(): boolean {
  for (const node of surfaces.keys()) {
    if (node.isConnected) return true;
  }
  return false;
}
