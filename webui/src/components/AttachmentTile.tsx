import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Download } from "lucide-react";

import { cn } from "@/lib/utils";
import type { UIMediaAttachment } from "@/lib/types";
import { ImageThumbnail } from "@/components/ImageGallery";
import { ImageLightbox } from "@/components/ImageLightbox";
import { useRegisterInlineImage } from "@/components/InlineImageContext";
import { AttachmentCard, AttachmentTypeFace, attachmentCardActionClassName } from "@/components/AttachmentCard";

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
  const name = attachment.name || label;
  const available = hasUrl && !failed;
  const status = available ? undefined : pending ? t("message.delivery.sending") : t("message.attachmentUnavailable");
  const download = available ? <a href={attachment.url} download={name} title={name}
    aria-label={t("message.downloadAttachment", { name })}
    className={cn(attachmentCardActionClassName, "text-muted-foreground hover:text-foreground")}>
    <Download aria-hidden strokeWidth={1.75} className="size-4" />
  </a> : undefined;

  return <span data-file-attachment className={cn("not-prose inline-flex w-24 max-w-full shrink-0 flex-col gap-1 align-top", className)}>
    <AttachmentCard name={name} description={status} action={download}>
      <AttachmentTypeFace name={filePath} kind={attachment.kind} />
    </AttachmentCard>
    {status ? <span className="break-words text-center text-[11px] leading-4 text-muted-foreground">{status}</span> : null}
    {attachment.kind === "video" && failed && !pending ? (
      <button type="button" onClick={() => setFailedUrl(undefined)}
        className="min-h-11 rounded-sm px-1 text-xs text-foreground underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2">
        {t("common.retry")}
      </button>
    ) : null}
  </span>;
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
