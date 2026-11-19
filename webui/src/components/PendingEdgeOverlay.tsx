import { useCallback, useEffect, useState } from "react";
import type { InputProcessingStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export type PendingEdgeState = "solid" | "pending" | "sealing";

const SEAL_FALLBACK_MS = 560;

/**
 * Tracks the visual edge lifecycle for queued user messages:
 * - "pending" while waiting in queue (dashed with subtle breathing)
 * - "cancelled" when stopped before consumption (static dashed)
 * - "sealing" for a single transition when a live message moves pending -> consumed
 * - "solid" at rest (including historical messages loaded as consumed)
 */
export function usePendingEdgeState(
  messageId: string,
  processingStatus: InputProcessingStatus | undefined,
  disabled: boolean,
): { edgeState: PendingEdgeState; completeSeal: () => void } {
  const [tracked, setTracked] = useState<{
    id: string;
    status: InputProcessingStatus | undefined;
    sealing: boolean;
  }>({
    id: messageId,
    status: processingStatus,
    sealing: false,
  });

  if (tracked.id !== messageId || tracked.status !== processingStatus) {
    const shouldSeal =
      !disabled &&
      tracked.id === messageId &&
      ((tracked.status === "pending" && processingStatus === "consumed") ||
        (tracked.sealing && processingStatus === undefined));
    setTracked({
      id: messageId,
      status: processingStatus,
      sealing: shouldSeal,
    });
  }

  const edgeState: PendingEdgeState = disabled
    ? "solid"
    : processingStatus === "pending"
      ? "pending"
      : tracked.sealing
        ? "sealing"
        : "solid";

  const completeSeal = useCallback(() => {
    setTracked((prev) => (prev.sealing ? { ...prev, sealing: false } : prev));
  }, []);

  useEffect(() => {
    if (edgeState !== "sealing") return;
    const timer = window.setTimeout(completeSeal, SEAL_FALLBACK_MS);
    return () => window.clearTimeout(timer);
  }, [edgeState, completeSeal]);

  return { edgeState, completeSeal };
}

export function PendingEdgeOverlay({
  state,
  solidTone = "bubble",
  inset = "inset-0",
  onSealEnd,
}: {
  state: PendingEdgeState;
  solidTone?: "bubble" | "card" | "media";
  inset?: string;
  onSealEnd?: () => void;
}) {
  if (state === "solid") return null;

  return (
    <span
      aria-hidden="true"
      data-pending-edge-overlay={state}
      data-solid-tone={solidTone}
      className={cn("pending-edge-overlay", inset)}
      onAnimationEnd={(event) => {
        if (
          state === "sealing" &&
          (event.animationName === "pending-edge-seal" ||
            event.animationName === "pending-edge-fade-out")
        ) {
          onSealEnd?.();
        }
      }}
    >
      <span className="pending-edge-layer pending-edge-layer-dashed" />
      {state === "sealing" ? (
        <>
          <span className="pending-edge-layer pending-edge-layer-solid" />
          <span className="pending-edge-layer pending-edge-layer-sheen" />
        </>
      ) : null}
    </span>
  );
}
