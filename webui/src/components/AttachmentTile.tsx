import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Download } from "lucide-react";

import { cn } from "@/lib/utils";
import type { UIMediaAttachment } from "@/lib/types";
import { ImageThumbnail } from "@/components/ImageGallery";
import { ImageLightbox } from "@/components/ImageLightbox";
import { useRegisterInlineImage } from "@/components/InlineImageContext";
import { FileReferenceIcon, fileKindForPath } from "@/components/FileReferenceChip";

interface AttachmentTileProps {
  attachment: UIMediaAttachment;
  className?: string;
  inline?: boolean;
  variant?: "default" | "compact";
  pending?: boolean;
}

export function AttachmentTile({ attachment, className, inline = false, variant = "default", pending = false }: AttachmentTileProps) {
  const { t } = useTranslation();
  const videoUrl = attachment.url;
  const [failedUrl, setFailedUrl] = useState<string | undefined>(undefined);
  const failed = !!videoUrl && failedUrl === videoUrl;
  const [imageOpen, setImageOpen] = useState(false);
  const hasUrl = typeof attachment.url === "string" && attachment.url.length > 0;
  const label = attachmentLabel(attachment, t);
  useRegisterInlineImage(inline && attachment.kind === "image" && hasUrl && !failed ? attachment.url : undefined);

  if (attachment.kind === "image" && hasUrl && !failed) {
    return (
      <span className={cn("not-prose my-3 block max-w-full", className)}>
        <ImageThumbnail key={attachment.url} image={attachment}
          size={variant === "compact" ? "compact" : "large"}
          onOpen={() => setImageOpen(true)} onError={() => setFailedUrl(attachment.url)} />
        <ImageLightbox images={[attachment]} index={imageOpen ? 0 : null}
          onIndexChange={() => {}} onOpenChange={setImageOpen} />
      </span>
    );
  }

  if (attachment.kind === "video" && hasUrl && !failed) {
    return (
      <AttachmentFrame
        attachment={attachment}
        className={className}
        inline={inline}
        variant={variant}
      >
        <video
          src={videoUrl}
          controls
          preload="metadata"
          onError={() => setFailedUrl(videoUrl)}
          className={cn(
            "block w-full bg-black",
            variant === "compact" ? "max-h-40" : "max-h-[26rem]",
          )}
          aria-label={attachment.name ? `${t("message.videoAttachment", { defaultValue: "Video attachment" })}: ${attachment.name}` : t("message.videoAttachment", { defaultValue: "Video attachment" })}
        />
      </AttachmentFrame>
    );
  }

  const filePath = attachment.name || attachment.url?.split(/[?#]/, 1)[0] || "";
  const fileKind = attachment.kind === "file" ? fileKindForPath(filePath) : attachment.kind;
  const name = attachment.name || label;
  const available = hasUrl && !failed;
  const extension = attachment.name?.match(/\.(tar\.(?:gz|bz2|xz)|[a-z0-9]{1,12})$/i)?.[1];
  const details = available ? extension?.toUpperCase() || label
    : pending ? t("message.delivery.sending") : t("message.attachmentUnavailable", { defaultValue: "Attachment unavailable" });
  const cardClassName = cn(
    "not-prose flex w-72 min-w-0 max-w-full items-center gap-3 rounded-control",
    "border border-border/60 bg-muted/40 px-3 py-2.5 text-sm text-muted-foreground",
    variant === "compact" && "w-56 gap-2 px-2.5 py-2 text-xs",
    className,
  );
  const body = (
    <>
      <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-compact bg-background/70", variant === "compact" && "size-8")}>
        <FileReferenceIcon kind={fileKind} className={variant === "compact" ? "size-4" : "size-5"} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium text-foreground">{name}</span>
        <span className="block break-words text-xs leading-4">{details}</span>
      </span>
    </>
  );

  if (available) {
    return (
      <a
        href={attachment.url}
        download={name}
        title={name}
        aria-label={t("message.downloadAttachment", { name })}
        className={cn(
          cardClassName,
          "transition-colors hover:bg-muted/55 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        )}
      >
        {body}
        <Download aria-hidden strokeWidth={1.75} className="size-4 shrink-0" />
      </a>
    );
  }

  const Frame = inline ? "span" : "div";
  return (
    <Frame className={cardClassName} title={name} aria-label={attachment.name ? `${label}: ${name}` : label}>
      {body}
      {attachment.kind === "video" && failed && !pending ? (
        <button type="button" onClick={() => setFailedUrl(undefined)}
          className="shrink-0 rounded-sm px-1 text-foreground underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2">
          {t("common.retry")}
        </button>
      ) : null}
    </Frame>
  );
}

function AttachmentFrame({
  attachment,
  children,
  className,
  inline = false,
  variant = "default",
}: {
  attachment: UIMediaAttachment;
  children: ReactNode;
  className?: string;
  inline?: boolean;
  variant?: "default" | "compact";
}) {
  const frameClassName = cn(
    "not-prose my-3 block w-fit max-w-full overflow-hidden rounded-control",
    "border border-border/60 bg-muted/40",
    attachment.kind === "image" && "bg-background/85",
    attachment.kind === "video" ? "w-[min(100%,32rem)]" : "",
    variant === "compact" && "my-1 rounded-xl shadow-none",
    variant === "compact" && attachment.kind === "video" && "w-[min(100%,20rem)]",
    className,
  );
  const bodyClassName = "block max-w-full";
  const body = inline ? (
    <span className={bodyClassName}>{children}</span>
  ) : (
    <div className={bodyClassName}>{children}</div>
  );
  return inline ? (
    <span className={frameClassName}>
      {body}
    </span>
  ) : (
    <figure className={frameClassName}>
      {body}
    </figure>
  );
}

function attachmentLabel(attachment: UIMediaAttachment, t: ReturnType<typeof useTranslation>["t"]): string {
  if (attachment.kind === "video") {
    return t("message.videoAttachment", { defaultValue: "Video attachment" });
  }
  if (attachment.kind === "image") {
    return t("message.imageAttachment", { defaultValue: "Image attachment" });
  }
  return t("message.fileAttachment", { defaultValue: "File attachment" });
}
