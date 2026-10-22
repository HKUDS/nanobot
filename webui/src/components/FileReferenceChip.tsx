import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type HTMLAttributes } from "react";
import { File, FileCode2, FileImage, FileJson2, FileText, FileVideo2, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { FileActions, useFilePreviewLoader } from "@/components/FileActions";
import { inferMediaKind } from "@/lib/media";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type FileReferenceKind =
  | "default"
  | "css"
  | "html"
  | "image"
  | "javascript"
  | "json"
  | "markdown"
  | "notebook"
  | "python"
  | "react"
  | "text"
  | "typescript"
  | "video";

interface FileReferenceChipProps {
  path: string;
  tooltipPath?: string;
  display?: "name" | "path";
  showIcon?: boolean;
  truncateFromStart?: boolean;
  active?: boolean;
  className?: string;
  textClassName?: string;
  previewPath?: string;
  onOpen?: (path: string) => void;
  testId?: string;
}

export function FileReferenceChip({
  path,
  tooltipPath,
  display = "name",
  showIcon = true,
  truncateFromStart = false,
  active = false,
  className,
  textClassName,
  previewPath,
  onOpen,
  testId = "inline-file-path",
}: FileReferenceChipProps) {
  const { t } = useTranslation();
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const { directory, name } = splitFilePath(path);
  const displayText = display === "path" ? path.replace(/\\/g, "/") : name;
  const fullPath = tooltipPath || path;
  const targetPath = previewPath || tooltipPath || path;
  const kind = fileKindForPath(targetPath);
  const interactive = Boolean(onOpen);
  const imageQuickLook = kind === "image" && interactive;
  const openPreview = (event: MouseEvent | KeyboardEvent) => {
    if (!onOpen) return;
    event.preventDefault();
    event.stopPropagation();
    setTooltipOpen(false);
    onOpen(targetPath);
  };
  const Text = truncateFromStart ? StartTruncatedText : "span";
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    openPreview(event);
  };
  return (
    <FileActions path={targetPath} className={truncateFromStart ? "min-w-0" : undefined}>
    <TooltipProvider>
      <Tooltip open={tooltipOpen} onOpenChange={setTooltipOpen}>
        <TooltipTrigger asChild>
          <span
            onContextMenuCapture={() => setTooltipOpen(false)}
            className={cn("not-prose inline-flex max-w-full align-baseline leading-[inherit]", truncateFromStart && "min-w-0", className)}
          >
            <span
              data-testid={testId}
              aria-label={fullPath}
              role={interactive ? "button" : undefined}
              tabIndex={interactive ? 0 : undefined}
              onClick={interactive ? openPreview : undefined}
              onKeyDown={interactive ? onKeyDown : undefined}
              className={cn(
                "inline-flex max-w-full items-baseline gap-[0.28em] font-medium leading-[inherit]",
                truncateFromStart && "min-w-0",
                interactive
                  ? "text-sky-600 transition-colors hover:text-sky-700 dark:text-sky-300 dark:hover:text-sky-200"
                  : "text-muted-foreground",
                interactive && [
                  "cursor-pointer rounded-compact",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/45",
                ],
              )}
            >
              {showIcon ? <FileReferenceIcon kind={kind} className="translate-y-[0.12em]" /> : null}
              <Text
                data-sheen-text={active ? displayText : undefined}
                className={cn(
                  "min-w-0 max-w-full",
                  !truncateFromStart && "[overflow-wrap:anywhere] sm:truncate",
                  active && !truncateFromStart && "streaming-text-sheen file-reference-sheen",
                  textClassName,
                )}
              >
                {display === "path" && directory ? (
                  <>
                    <span className="text-muted-foreground">{directory}</span>
                    <span className={cn("font-semibold", interactive && "text-sky-700 dark:text-sky-200")}>{name}</span>
                  </>
                ) : (
                  displayText
                )}
              </Text>
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent
          aria-label={truncateFromStart ? fullPath : imageQuickLook ? t("filePreview.aria") : undefined}
          side="top"
          align={truncateFromStart ? "start" : "center"}
          sideOffset={8}
          collisionPadding={12}
          className={cn(
            "rounded-control text-popover-foreground",
            imageQuickLook && truncateFromStart && "space-y-2",
            imageQuickLook
              ? cn("w-max p-2", truncateFromStart ? "max-w-[min(38rem,calc(100vw-2rem))]" : "max-w-[calc(100vw-2rem)]")
              : cn("max-w-[min(38rem,calc(100vw-2rem))] px-2.5 py-1.5 font-mono text-[11px] leading-snug", truncateFromStart ? "text-left [overflow-wrap:anywhere]" : "break-all"),
          )}
        >
          {truncateFromStart ? <span className="block max-w-full select-text whitespace-pre-wrap text-left font-mono text-[11px] leading-snug [overflow-wrap:anywhere]">{fullPath.split(/([\\/])/).map((part, index) => (
            <span key={index}>{part}{/^[\\/]$/.test(part) ? <wbr /> : null}</span>
          ))}</span> : !imageQuickLook ? fullPath : null}
          {imageQuickLook && tooltipOpen ? <FileImageQuickLook key={targetPath} path={targetPath} /> : null}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
    </FileActions>
  );
}

function StartTruncatedText({ children, className, ...props }: HTMLAttributes<HTMLSpanElement> & { "data-sheen-text"?: string }) {
  const container = useRef<HTMLSpanElement>(null);
  const content = useRef<HTMLSpanElement>(null);
  const [clipped, setClipped] = useState(false);
  useLayoutEffect(() => {
    const update = () => setClipped(content.current!.getBoundingClientRect().width > container.current!.getBoundingClientRect().width);
    const observer = new ResizeObserver(update);
    observer.observe(container.current!);
    observer.observe(content.current!);
    update();
    return () => observer.disconnect();
  }, []);
  return <span ref={container} className={cn("inline-flex items-baseline overflow-hidden whitespace-nowrap", className)}>
    {clipped ? <span aria-hidden className="shrink-0">…</span> : null}
    <span className="flex min-w-0 justify-end overflow-hidden">
      <span ref={content} className={cn("shrink-0", props["data-sheen-text"] && "streaming-text-sheen file-reference-sheen")} {...props}>{children}</span>
    </span>
  </span>;
}

/** Only loads after the normal hover/focus delay, through the session's guarded preview API. */
function FileImageQuickLook({ path }: { path: string }) {
  const { t } = useTranslation();
  const load = useFilePreviewLoader();
  const [result, setResult] = useState<{ load: typeof load; source: string | null }>();
  const source = result?.load === load ? result?.source : undefined;
  useEffect(() => {
    let cancelled = false;
    void load?.(path).then((payload) => {
      if (!cancelled) setResult({ load, source: payload.kind === "image" ? payload.data_url : null });
    }).catch(() => { if (!cancelled) setResult({ load, source: null }); });
    return () => { cancelled = true; };
  }, [path, load]);
  if (!load || source === null) return <span className="block px-1 py-1 text-xs text-muted-foreground">
    {t("filePreview.failed", { defaultValue: "Could not preview this file." })}
  </span>;
  return <span data-testid="file-image-quick-look" className="block w-max max-w-full overflow-hidden rounded-mark" aria-hidden>
    {source ? <img src={source} alt="" decoding="async" draggable={false}
      className="block h-auto max-h-36 w-auto max-w-[min(14rem,calc(100vw-3rem))] rounded-mark object-contain" onError={() => setResult({ load, source: null })} />
      : <span className="block h-36 w-56 max-w-[calc(100vw-3rem)] animate-pulse bg-muted/40 motion-reduce:animate-none" />}
  </span>;
}

export function isLikelyFilePath(value: string): boolean {
  const raw = value.trim();
  if (!raw || raw.includes("\n")) return false;
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(raw)) return false;
  if (isFilePatternReference(raw)) return false;
  if (!/[\\/]/.test(raw) && !/^(dockerfile|makefile|readme|package-lock\.json)$/i.test(raw)) {
    return false;
  }
  const normalized = raw.replace(/\\/g, "/");
  const name = normalized.split("/").filter(Boolean).pop() ?? normalized;
  if (!name || name === "." || name === "..") return false;
  if (/^(dockerfile|makefile|readme|package-lock\.json)$/i.test(name)) return true;
  return /\.[a-z0-9][a-z0-9_-]{0,12}$/i.test(name);
}

export function isFilePatternReference(value: string): boolean {
  return /[*?[\]{}]/.test(value.trim());
}

export function splitFilePath(path: string): { directory: string; name: string } {
  const normalized = path.replace(/\\/g, "/");
  const slash = normalized.lastIndexOf("/");
  if (slash < 0) return { directory: "", name: path };
  return {
    directory: normalized.slice(0, slash + 1),
    name: normalized.slice(slash + 1) || normalized,
  };
}

export function fileKindForPath(path: string): FileReferenceKind {
  const mediaKind = inferMediaKind({ url: path });
  if (mediaKind === "image" || mediaKind === "video") return mediaKind;
  const normalized = path.toLowerCase();
  const name = normalized.split(/[\\/]/).pop() ?? normalized;
  const ext = name.includes(".") ? name.split(".").pop() ?? "" : "";
  if (name === "dockerfile") {
    return "default";
  }
  switch (ext) {
    case "avif":
      return "image";
    case "py":
    case "pyi":
      return "python";
    case "jsx":
    case "tsx":
      return "react";
    case "js":
    case "mjs":
    case "cjs":
      return "javascript";
    case "ts":
    case "mts":
    case "cts":
      return "typescript";
    case "html":
    case "htm":
      return "html";
    case "css":
    case "scss":
    case "sass":
      return "css";
    case "json":
    case "jsonl":
      return "json";
    case "md":
    case "mdx":
      return "markdown";
    case "ipynb":
      return "notebook";
    case "txt":
    case "log":
      return "text";
    default:
      return "default";
  }
}

const FILE_ICONS = {
  default: File,
  css: FileCode2,
  html: FileCode2,
  image: FileImage,
  javascript: FileCode2,
  json: FileJson2,
  markdown: FileText,
  notebook: FileCode2,
  python: FileCode2,
  react: FileCode2,
  text: FileText,
  typescript: FileCode2,
  video: FileVideo2,
} satisfies Record<FileReferenceKind, LucideIcon>;

export function fileIconForPath(path: string): LucideIcon {
  return FILE_ICONS[fileKindForPath(path)];
}

/** The same file silhouette and stroke in replies, tabs, and attachment tiles. */
export function FileReferenceIcon({ kind, className }: { kind: FileReferenceKind; className?: string }) {
  const Icon = FILE_ICONS[kind];
  return <Icon aria-hidden strokeWidth={1.75} className={cn("h-[1em] w-[1em] shrink-0", className)} />;
}
