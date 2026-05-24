import { useCallback, useEffect, useMemo } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { UIImage } from "@/lib/types";

interface ImageLightboxProps {
  images: UIImage[];
  index: number | null;
  onIndexChange: (index: number) => void;
  onOpenChange: (open: boolean) => void;
}

/**
 * Modal image viewer. Uses the Radix Dialog primitives directly so we can
 * fill the viewport (the shared `DialogContent` wrapper caps at max-w-lg,
 * which is much too small for a photo preview).
 *
 * Implementation notes:
 * - `translate3d` + `will-change: transform` promote the image to a GPU
 *   compositing layer so open/swap stays at 60 FPS on long threads.
 * - Adjacent images are rendered in hidden `<img>` tags so the browser
 *   decodes them eagerly; pressing left/right feels instant.
 * - Radix handles `Escape` + focus trapping; we only wire up ←/→ + Home/End.
 * - Respects `prefers-reduced-motion` by dropping the fade + zoom-in
 *   keyframes via `motion-reduce:*` variants.
 */
export function ImageLightbox({
  images,
  index,
  onIndexChange,
  onOpenChange,
}: ImageLightboxProps) {
  const { t } = useTranslation();
  const open = index !== null;
  const total = images.length;
  const current = index !== null ? images[index] : null;

  const go = useCallback(
    (delta: number) => {
      if (index === null || total <= 1) return;
      const next = (index + delta + total) % total;
      onIndexChange(next);
    },
    [index, onIndexChange, total],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        go(-1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        go(1);
      } else if (e.key === "Home") {
        e.preventDefault();
        onIndexChange(0);
      } else if (e.key === "End") {
        e.preventDefault();
        onIndexChange(total - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, onIndexChange, open, total]);

  // Neighbours we want the browser to decode eagerly.
  const preload = useMemo(() => {
    if (index === null || total <= 1) return [] as UIImage[];
    const prev = images[(index - 1 + total) % total];
    const next = images[(index + 1) % total];
    return [prev, next].filter((i) => i && i.url);
  }, [images, index, total]);

  if (!current || !current.url) return null;

  const hasMany = total > 1;
  const counter = hasMany ? `${index! + 1} / ${total}` : null;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className={cn(
            "fixed inset-0 z-50 bg-black/80 backdrop-blur-sm",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
            "motion-reduce:data-[state=open]:animate-none motion-reduce:data-[state=closed]:animate-none",
          )}
        />
        <DialogPrimitive.Content
          aria-label={current.name ?? t("lightbox.title")}
          className={cn(
            "fixed inset-0 z-50 flex items-center justify-center",
            "focus:outline-none",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
            "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
            "motion-reduce:data-[state=open]:animate-none motion-reduce:data-[state=closed]:animate-none",
          )}
        >
          <DialogPrimitive.Title className="sr-only">
            {current.name ?? t("lightbox.title")}
          </DialogPrimitive.Title>

          <div
            className="relative flex max-h-[92vh] max-w-[94vw] items-center justify-center"
            style={{
              transform: "translate3d(0,0,0)",
              willChange: "transform",
            }}
          >
            <img
              key={current.url}
              src={current.url}
              alt={current.name ?? ""}
              decoding="async"
              draggable={false}
              className="max-h-[92vh] max-w-[94vw] select-none rounded-[6px] object-contain shadow-2xl"
            />
          </div>

          {hasMany ? (
            <>
              <NavButton
                side="left"
                label={t("lightbox.prev")}
                onClick={(e) => {
                  e.stopPropagation();
                  go(-1);
                }}
              />
              <NavButton
                side="right"
                label={t("lightbox.next")}
                onClick={(e) => {
                  e.stopPropagation();
                  go(1);
                }}
              />
              <div className="pointer-events-none absolute bottom-5 left-1/2 -translate-x-1/2 rounded-full bg-black/55 px-3 py-1 text-xs font-medium text-white/90 tabular-nums">
                {counter}
              </div>
            </>
          ) : null}

          <DialogPrimitive.Close
            aria-label={t("lightbox.close")}
            className={cn(
              "absolute right-4 top-4 grid h-9 w-9 place-items-center rounded-full",
              "bg-black/55 text-white/90 hover:bg-black/70 hover:text-white",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70",
              "transition-colors motion-reduce:transition-none",
            )}
          >
            <X className="h-4 w-4" aria-hidden />
          </DialogPrimitive.Close>

          {/* Invisible preload — browser decodes adjacent images so prev/next swap is instant. */}
          <div aria-hidden className="hidden">
            {preload.map((img, i) => (
              <img key={`${img.url}-${i}`} src={img.url} alt="" />
            ))}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

interface NavButtonProps {
  side: "left" | "right";
  label: string;
  onClick: React.MouseEventHandler<HTMLButtonElement>;
}

function NavButton({ side, label, onClick }: NavButtonProps) {
  const Icon = side === "left" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={cn(
        "absolute top-1/2 -translate-y-1/2 grid h-11 w-11 place-items-center rounded-full",
        "bg-black/55 text-white/90 hover:bg-black/70 hover:text-white",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70",
        "transition-colors motion-reduce:transition-none",
        side === "left" ? "left-4" : "right-4",
      )}
    >
      <Icon className="h-5 w-5" aria-hidden />
    </button>
  );
}
