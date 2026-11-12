import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import * as Menu from "@radix-ui/react-menu";
import { useTranslation } from "react-i18next";

import { floatingItemClassName, floatingItemFocusClassName, floatingSurfaceClassName, floatingSurfaceMotionClassName } from "@/components/ui/floating-surface";
import { useFloatingPortal } from "@/components/ui/floating-portal";
import { copyTextToClipboard } from "@/lib/clipboard";
import type { FileReferenceMetadata, FilePreviewPayload } from "@/lib/types";
import { cn } from "@/lib/utils";

interface FileActionsContextValue {
  resolveMetadata: (path: string) => Promise<FileReferenceMetadata>;
  loadPreview?: (path: string) => Promise<FilePreviewPayload>;
}

const FileActionsContext = createContext<FileActionsContextValue | undefined>(undefined);

export const FileActionsProvider = FileActionsContext.Provider;

export function useFilePreviewLoader() {
  return useContext(FileActionsContext)?.loadPreview;
}

const itemClassName = `${floatingItemClassName} ${floatingItemFocusClassName} cursor-default data-[disabled]:pointer-events-none data-[disabled]:opacity-50`;

/** Copy-only context menu, shared by file references and preview tabs. */
export function FileActions({
  path, children, metadata, className,
}: {
  path: string;
  children: ReactNode;
  metadata?: FileReferenceMetadata;
  className?: string;
}) {
  const context = useContext(FileActionsContext);
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [resolved, setResolved] = useState<FileReferenceMetadata | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [copyStatus, setCopyStatus] = useState<"copied" | "failed" | null>(null);
  const resolveMetadata = context?.resolveMetadata;
  const portal = useFloatingPortal();
  const point = useRef({ x: 0, y: 0 });
  const anchor = useRef({ getBoundingClientRect: () => new DOMRect(point.current.x, point.current.y, 0, 0) });
  const opener = useRef<HTMLElement | null>(null);
  const interactedOutside = useRef(false);
  const copyGeneration = useRef(0);

  const changeOpen = (next: boolean) => {
    copyGeneration.current += 1;
    setOpen(next);
  };

  useEffect(() => {
    let cancelled = false;
    setResolved(metadata ?? null);
    setLoadFailed(false);
    setCopyStatus(null);
    if (open && !metadata && resolveMetadata) {
      void resolveMetadata(path).then((value) => {
        if (typeof value.path !== "string" || !(value.relative_path === null || typeof value.relative_path === "string")) {
          throw new Error("File metadata is unavailable on this gateway");
        }
        if (!cancelled) setResolved(value);
      }).catch(() => { if (!cancelled) setLoadFailed(true); });
    }
    return () => { cancelled = true; copyGeneration.current += 1; };
  }, [open, path, metadata, resolveMetadata]);

  const copy = async (value: string) => {
    const generation = ++copyGeneration.current;
    const success = await copyTextToClipboard(value);
    // A dismissed/reopened menu or another reference owns its own feedback.
    if (generation !== copyGeneration.current) return;
    setCopyStatus(success ? "copied" : "failed");
    if (success) changeOpen(false);
  };
  const openMenu = (target: EventTarget, x: number, y: number) => {
    point.current = { x, y };
    opener.current = target instanceof Element ? target.closest<HTMLElement>("button, a, [tabindex]") : null;
    interactedOutside.current = false;
    changeOpen(true);
  };
  const status = copyStatus ?? (loadFailed ? "unavailable" : !resolved && resolveMetadata ? "loading" : null);

  return (
    <Menu.Root open={open} onOpenChange={changeOpen}>
      <Menu.Anchor virtualRef={anchor} />
      <span
        className={cn("not-prose inline-flex max-w-full items-baseline align-baseline", className)}
        onContextMenu={(event) => {
          event.preventDefault();
          event.stopPropagation();
          openMenu(event.target, event.clientX, event.clientY);
        }}
        onKeyDown={(event) => {
          if (event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey)) {
            event.preventDefault();
            event.stopPropagation();
            const bounds = event.currentTarget.getBoundingClientRect();
            openMenu(event.target, bounds.left, bounds.bottom);
          }
        }}
      >
        {children}
      </span>
      <Menu.Portal container={portal ?? undefined}>
        <Menu.Content aria-label={t("fileActions.menu", { name: path.split(/[\\/]/).pop() || path })}
          align="start" sideOffset={4} collisionPadding={12}
          className={cn(floatingSurfaceClassName, floatingSurfaceMotionClassName, "min-w-40 rounded-control p-1 [&_[role=menuitem]]:py-1.5")}
          onClick={(event) => event.stopPropagation()}
          onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); }}
          onInteractOutside={() => { interactedOutside.current = true; }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (!interactedOutside.current) opener.current?.focus();
          }}>
          <Menu.Item className={itemClassName} disabled={!resolved} onSelect={(event) => {
            event.preventDefault();
            if (resolved) void copy(resolved.path);
          }}>
            {t("fileActions.copyAbsolute")}
          </Menu.Item>
          <Menu.Item className={itemClassName} disabled={!resolved?.relative_path} onSelect={(event) => {
            event.preventDefault();
            if (resolved?.relative_path) void copy(resolved.relative_path);
          }}>
            {t("fileActions.copyRelative")}
          </Menu.Item>
          {!resolved ? <Menu.Item className={itemClassName} onSelect={(event) => {
            event.preventDefault();
            void copy(path);
          }}>{t("fileActions.copyReference")}</Menu.Item> : null}
          {status ? <div role="status" className="max-w-64 px-2.5 py-1.5 text-xs text-muted-foreground">
            {t(`fileActions.${status}`)}
          </div> : null}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
