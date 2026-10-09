import { useState } from "react";
import { ImageIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ImageLightbox } from "@/components/ImageLightbox";
import type { UIImage } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A bounded, quiet preview; the viewer still contains every delivered image. */
export function ImageGallery({ images, align = "left", size = "large" }: {
  images: UIImage[];
  align?: "left" | "right";
  size?: "compact" | "large";
}) {
  const { t } = useTranslation();
  const [index, setIndex] = useState<number | null>(null);
  const viewable = images.filter((image) => image.url);
  const multiple = images.length > 1;
  const visible = images.slice(0, 4);
  return <>
    <span className={cn(
      "max-w-full gap-2",
      multiple && size === "large" ? "grid w-[28rem] grid-cols-2" : "flex flex-wrap items-end",
      align === "right" ? "ml-auto justify-end" : "mr-auto justify-start",
    )}>
      {visible.map((image, position) => {
        const remaining = images.length - visible.length;
        const overflow = position === visible.length - 1 && remaining > 0;
        return <ImageThumbnail key={`${image.url ?? image.name}-${position}`}
          image={image} size={multiple && size === "large" ? "grid" : size}
          label={overflow ? t("lightbox.viewAll", { count: images.length }) : undefined}
          onOpen={image.url || (overflow && viewable.length) ? () => setIndex(Math.max(0, viewable.indexOf(image))) : undefined}
          overlay={overflow ? `+${remaining}` : undefined} />;
      })}
    </span>
    <ImageLightbox images={viewable} index={index} onIndexChange={setIndex}
      onOpenChange={(open) => { if (!open) setIndex(null); }} />
  </>;
}

export function ImageThumbnail({ image, size = "large", onOpen, label, overlay, onError }: {
  image: UIImage;
  size?: "compact" | "large" | "grid";
  onOpen?: () => void;
  label?: string;
  overlay?: string;
  onError?: () => void;
}) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  const classes = cn(
    "relative block max-w-full overflow-hidden rounded-control border border-border/60 bg-muted/25",
    size === "large" ? "w-[min(100%,28rem)]" : size === "grid" ? "aspect-[8/5] w-full" : "h-24 w-24",
  );
  const content = image.url && !failed ? <img src={image.url} alt={image.name ?? ""}
    loading="lazy" decoding="async" draggable={false}
    onError={() => { setFailed(true); onError?.(); }}
    className={cn("block w-full object-contain", size === "large" ? "h-auto max-h-[22rem]" : "h-full")} />
    : <span className={cn("flex min-h-24 items-center justify-center gap-2 px-3 py-5 text-xs text-muted-foreground", size === "grid" && "h-full")}
      aria-label={t("message.attachmentUnavailable")}>
      <ImageIcon className="h-4 w-4 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">{image.name || t("message.imageAttachment")}</span>
    </span>;
  if (!onOpen || ((!image.url || failed) && !overlay)) return <span className={classes}>{content}</span>;
  return <button type="button" onClick={onOpen}
    aria-label={label ?? (image.name ? `${t("lightbox.open")}: ${image.name}` : t("lightbox.open"))}
    className={cn(classes, "cursor-zoom-in p-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background")}>
    {content}
    {overlay ? <span className="absolute inset-0 flex items-center justify-center bg-black/45 text-xl font-medium text-white" aria-hidden>{overlay}</span> : null}
  </button>;
}
