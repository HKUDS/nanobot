import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type FileReferenceKind =
  | "default"
  | "css"
  | "html"
  | "json"
  | "markdown"
  | "notebook"
  | "python"
  | "react"
  | "typescript";

interface FileReferenceChipProps {
  path: string;
  tooltipPath?: string;
  display?: "name" | "path";
  active?: boolean;
  className?: string;
  textClassName?: string;
  testId?: string;
}

export function FileReferenceChip({
  path,
  tooltipPath,
  display = "name",
  active = false,
  className,
  textClassName,
  testId = "inline-file-path",
}: FileReferenceChipProps) {
  const { directory, name } = splitFilePath(path);
  const kind = fileKindForPath(path);
  const displayText = display === "path" ? path.replace(/\\/g, "/") : name;
  const fullPath = tooltipPath || path;
  return (
    <TooltipProvider delayDuration={500} skipDelayDuration={100}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn("not-prose inline-flex max-w-full align-baseline leading-[inherit]", className)}
          >
            <span
              data-testid={testId}
              aria-label={fullPath}
              className={cn(
                "inline-flex max-w-full items-baseline gap-[0.28em] font-medium leading-[inherit]",
                "text-sky-600 transition-colors hover:text-sky-700",
                "dark:text-sky-300 dark:hover:text-sky-200",
              )}
            >
              <FileReferenceIcon kind={kind} />
              <span
                data-sheen-text={active ? displayText : undefined}
                className={cn(
                  "min-w-0 max-w-full truncate",
                  active && "streaming-text-sheen file-reference-sheen",
                  textClassName,
                )}
              >
                {display === "path" && directory ? (
                  <>
                    <span className="text-muted-foreground/65">{directory}</span>
                    <span className="font-semibold text-sky-700 dark:text-sky-200">{name}</span>
                  </>
                ) : (
                  displayText
                )}
              </span>
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          align="center"
          sideOffset={8}
          collisionPadding={12}
          className={cn(
            "max-w-[min(38rem,calc(100vw-2rem))] rounded-[10px]",
            "border-border/60 bg-popover/95 px-2.5 py-1.5",
            "break-all font-mono text-[11px] leading-snug text-popover-foreground",
            "shadow-lg backdrop-blur",
          )}
        >
          {fullPath}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function isLikelyFilePath(value: string): boolean {
  const raw = value.trim();
  if (!raw || raw.includes("\n")) return false;
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(raw)) return false;
  if (!/[\\/]/.test(raw) && !/^(dockerfile|makefile|readme|package-lock\.json)$/i.test(raw)) {
    return false;
  }
  const normalized = raw.replace(/\\/g, "/");
  const name = normalized.split("/").filter(Boolean).pop() ?? normalized;
  if (!name || name === "." || name === "..") return false;
  if (/^(dockerfile|makefile|readme|package-lock\.json)$/i.test(name)) return true;
  return /\.[a-z0-9][a-z0-9_-]{0,12}$/i.test(name);
}

function splitFilePath(path: string): { directory: string; name: string } {
  const normalized = path.replace(/\\/g, "/");
  const slash = normalized.lastIndexOf("/");
  if (slash < 0) return { directory: "", name: path };
  return {
    directory: normalized.slice(0, slash + 1),
    name: normalized.slice(slash + 1) || normalized,
  };
}

function fileKindForPath(path: string): FileReferenceKind {
  const normalized = path.toLowerCase();
  const name = normalized.split(/[\\/]/).pop() ?? normalized;
  const ext = name.includes(".") ? name.split(".").pop() ?? "" : "";
  if (name === "dockerfile") {
    return "default";
  }
  switch (ext) {
    case "py":
    case "pyi":
      return "python";
    case "jsx":
    case "tsx":
      return "react";
    case "ts":
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
    default:
      return "default";
  }
}

function FileReferenceIcon({ kind }: { kind: FileReferenceKind }) {
  if (kind === "react") {
    return (
      <svg
        aria-hidden
        className="h-[0.92em] w-[0.92em] shrink-0 translate-y-[0.11em] text-sky-500 dark:text-sky-300"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="1.9" fill="currentColor" stroke="none" />
        <ellipse cx="12" cy="12" rx="9" ry="3.7" />
        <ellipse cx="12" cy="12" rx="9" ry="3.7" transform="rotate(60 12 12)" />
        <ellipse cx="12" cy="12" rx="9" ry="3.7" transform="rotate(120 12 12)" />
      </svg>
    );
  }
  if (kind === "default") {
    return (
      <svg
        aria-hidden
        className="h-[0.92em] w-[0.92em] shrink-0 translate-y-[0.11em] text-sky-500 dark:text-sky-300"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7z" />
        <path d="M14 2v5h5" />
      </svg>
    );
  }
  const label = fileKindLabel(kind);
  return (
    <svg
      aria-hidden
      className="h-[0.96em] w-[0.96em] shrink-0 translate-y-[0.12em] text-sky-500 dark:text-sky-300"
      viewBox="0 0 24 24"
      fill="none"
    >
      <path
        d="M7 3.5h6.6L18 7.9V19a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1.5-1.5Z"
        fill="currentColor"
        opacity="0.12"
      />
      <path
        d="M13.5 3.75V8h4.25M7 3.5h6.6L18 7.9V19a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1.5-1.5Z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <text
        x="12"
        y="15.7"
        textAnchor="middle"
        fill="currentColor"
        fontSize={label.length > 1 ? "5.8" : "7.2"}
        fontWeight="800"
        letterSpacing="-0.2"
      >
        {label}
      </text>
    </svg>
  );
}

function fileKindLabel(kind: FileReferenceKind): string {
  switch (kind) {
    case "css":
      return "#";
    case "html":
      return "H";
    case "json":
      return "{}";
    case "markdown":
      return "M";
    case "notebook":
      return "N";
    case "python":
      return "PY";
    case "typescript":
      return "TS";
    default:
      return "";
  }
}
