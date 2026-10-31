import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { ImageIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ImageLightbox } from "@/components/ImageLightbox";
import { IMAGE_GAP, imageFrameRatio, layoutImageRows, type ImageDimensions } from "@/lib/image-gallery-layout";
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
  const [dimensions, setDimensions] = useState<Record<string, ImageDimensions | null>>({});
  const [width, setWidth] = useState(0);
  const container = useRef<HTMLSpanElement>(null);
  const viewable = images.filter((image) => image.url);
  const visible = images.slice(0, 4);
  const measured = visible.map((image) => image.url ? dimensions[image.url] : null);
  const ready = measured.every((image) => image !== undefined);
  const maxWidth = size === "large" ? 448 : 360;
  const maxHeight = visible.length === 1 ? (size === "large" ? 352 : 320) : (size === "large" ? 256 : 224);
  const single = visible.length === 1 ? measured[0] : null;
  const preferredWidth = single ? Math.min(maxWidth, single.width, maxHeight * imageFrameRatio(single)) : maxWidth;

  useLayoutEffect(() => {
    const element = container.current;
    if (!element) return;
    const measure = () => setWidth(element.getBoundingClientRect().width);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [preferredWidth]);

  const layoutWidth = Math.min(width || preferredWidth, preferredWidth);
  const rows = layoutImageRows(
    ready ? measured : visible.map(() => null), layoutWidth,
    size === "large" ? 176 : 144, maxHeight,
  );
  let top = 0;
  const tiles = rows.flatMap((row) => {
    const rowWidth = row.widths.reduce((sum, item) => sum + item, IMAGE_GAP * (row.widths.length - 1));
    let left = align === "right" ? layoutWidth - rowWidth : 0;
    const items = row.widths.map((tileWidth, offset) => {
      const tile = { position: row.start + offset, frame: { width: tileWidth, height: row.height, left, top } };
      left += tileWidth + IMAGE_GAP;
      return tile;
    });
    top += row.height + IMAGE_GAP;
    return items;
  });
  const remember = (url: string, value: ImageDimensions | null) => setDimensions((current) => {
    const previous = current[url];
    if (previous === value || (previous && value && previous.width === value.width && previous.height === value.height)) return current;
    return { ...current, [url]: value };
  });

  return <>
    <span ref={container} data-image-gallery className={cn(
      "relative block max-w-full",
      align === "right" ? "ml-auto" : "mr-auto",
    )} style={{ width: preferredWidth, height: Math.max(0, top - IMAGE_GAP) }}>
      {tiles.map(({ position, frame }) => {
        const image = visible[position];
        const remaining = images.length - visible.length;
        const overflow = position === visible.length - 1 && remaining > 0;
        return <ImageThumbnail key={`${image.url ?? image.name}-${position}`}
          image={image} size={size} frame={frame}
          onLoad={(value) => { if (image.url) remember(image.url, value); }}
          onError={() => { if (image.url) remember(image.url, null); }}
          label={overflow ? t("lightbox.viewAll", { count: images.length }) : undefined}
          onOpen={image.url || (overflow && viewable.length) ? () => setIndex(Math.max(0, viewable.indexOf(image))) : undefined}
          overlay={overflow ? `+${remaining}` : undefined} />;
      })}
    </span>
    <ImageLightbox images={viewable} index={index} onIndexChange={setIndex}
      onOpenChange={(open) => { if (!open) setIndex(null); }} />
  </>;
}

export function ImageThumbnail({ image, size = "large", frame, onOpen, label, overlay, onLoad, onError }: {
  image: UIImage;
  size?: "compact" | "large";
  frame?: ImageDimensions & { left: number; top: number };
  onOpen?: () => void;
  label?: string;
  overlay?: string;
  onLoad?: (dimensions: ImageDimensions) => void;
  onError?: () => void;
}) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  const classes = cn(
    "relative block max-w-full shrink-0 overflow-hidden rounded-control bg-muted/25 ring-1 ring-inset ring-border/60",
    !frame && (size === "large" ? "w-[min(100%,28rem)]" : "w-48"),
  );
  const style: CSSProperties | undefined = frame ? { ...frame, position: "absolute" } : undefined;
  const unavailable = t("message.attachmentUnavailable");
  const content = image.url && !failed ? <img src={image.url} alt={image.name ?? ""}
    loading="lazy" decoding="async" draggable={false}
    onLoad={(event) => {
      const { naturalWidth, naturalHeight } = event.currentTarget;
      onLoad?.({ width: naturalWidth, height: naturalHeight });
    }}
    onError={() => { setFailed(true); onError?.(); }}
    className={cn("block w-full object-contain text-transparent", frame ? "h-full" : "h-auto max-h-[22rem]")} />
    : <span className={cn("flex items-center justify-center gap-2 px-3 text-xs text-muted-foreground", frame ? "h-full" : "min-h-24 py-5")}
      aria-label={image.name ? `${unavailable}: ${image.name}` : unavailable} title={image.name}>
      <ImageIcon className="h-4 w-4 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">{unavailable}</span>
    </span>;
  if (!onOpen || ((!image.url || failed) && !overlay)) return <span className={classes} style={style}>{content}</span>;
  return <button type="button" onClick={onOpen} style={style}
    aria-label={label ?? (image.name ? `${t("lightbox.open")}: ${image.name}` : t("lightbox.open"))}
    className={cn(classes, "cursor-zoom-in p-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background")}>
    {content}
    {overlay ? <span className="absolute inset-0 flex items-center justify-center bg-black/45 text-xl font-medium text-white" aria-hidden>{overlay}</span> : null}
  </button>;
}
