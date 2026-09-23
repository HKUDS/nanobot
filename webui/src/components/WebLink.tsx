import { createContext, useContext, useEffect, useRef, useState, type ComponentPropsWithoutRef } from "react";
import * as Menu from "@radix-ui/react-menu";
import { useTranslation } from "react-i18next";

import { floatingItemClassName, floatingItemFocusClassName, floatingSurfaceClassName, floatingSurfaceMotionClassName } from "@/components/ui/floating-surface";
import { useFloatingPortal } from "@/components/ui/floating-portal";
import { copyTextToClipboard } from "@/lib/clipboard";
import { parseWebLink } from "@/lib/web-preview";
import { cn } from "@/lib/utils";

export const WebPreviewContext = createContext<((url: string) => void) | undefined>(undefined);

const itemClassName = `${floatingItemClassName} ${floatingItemFocusClassName} cursor-default`;

export function WebLink({ href = "", children, ...props }: ComponentPropsWithoutRef<"a">) {
  const url = parseWebLink(href);
  if (url) return <WebsiteLink key={href} {...props} href={href}>{children}</WebsiteLink>;
  // Keep the renderer's relative media/document and mail links unchanged.
  const relative = !/^[a-z][a-z\d+.-]*:/i.test(href)
    && !href.includes("\\") && !Array.from(href).some((char) => char.charCodeAt(0) < 32);
  return relative || /^(mailto:|tel:|#)/i.test(href)
    ? <a {...props} href={href} target="_blank" rel="noreferrer noopener">{children}</a> : <>{children}</>;
}

/** Keep links as links; secondary actions share the compact file-reference surface. */
function WebsiteLink({ href, children, className, ...props }: ComponentPropsWithoutRef<"a"> & { href: string }) {
  const { t } = useTranslation();
  const openPreview = useContext(WebPreviewContext);
  const portal = useFloatingPortal();
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState<"copied" | "copyFailed" | null>(null);
  const link = useRef<HTMLAnchorElement>(null);
  const point = useRef({ x: 0, y: 0 });
  const anchor = useRef({ getBoundingClientRect: () => new DOMRect(point.current.x, point.current.y, 0, 0) });
  const interactedOutside = useRef(false);
  const generation = useRef(0);
  const pointerType = useRef("");

  useEffect(() => () => {
    generation.current += 1;
  }, []);

  const changeOpen = (next: boolean) => {
    generation.current += 1;
    setOpen(next);
  };
  const openAt = (x: number, y: number) => {
    point.current = { x, y };
    interactedOutside.current = false;
    setFeedback(null);
    changeOpen(true);
  };
  const copy = async () => {
    const current = generation.current;
    const copied = await copyTextToClipboard(href);
    // Late clipboard results must not dismiss a new menu or report another URL.
    if (current !== generation.current) return;
    setFeedback(copied ? "copied" : "copyFailed");
    if (copied) changeOpen(false);
  };

  return <Menu.Root open={open} onOpenChange={changeOpen}>
    <Menu.Anchor virtualRef={anchor} />
    <span className="inline max-w-full"
      onContextMenu={(event) => {
        event.stopPropagation();
        // Touch keeps the browser's native link preview/copy/share menu. Older
        // WebKit exposes contextmenu as a MouseEvent, so remember the last pointer.
        const type = (event.nativeEvent as PointerEvent).pointerType || pointerType.current;
        if (type === "touch" || (!type && window.matchMedia("(pointer: coarse)").matches)) return;
        event.preventDefault();
        openAt(event.clientX, event.clientY);
      }}
      onKeyDown={(event) => {
        if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return;
        event.preventDefault(); event.stopPropagation();
        const bounds = link.current!.getBoundingClientRect();
        openAt(bounds.left, bounds.bottom);
      }}
      onPointerDown={(event) => {
        pointerType.current = event.pointerType;
      }}>
      <a {...props} ref={link} data-web-link href={href} target="_blank" rel="noreferrer noopener"
        className={className}>{children}</a>
    </span>
    {feedback === "copied" ? <span role="status" className="sr-only">{t("webPreview.copied")}</span> : null}
    <Menu.Portal container={portal ?? undefined}>
      <Menu.Content aria-label={t("webPreview.actions")} align="start" sideOffset={4} collisionPadding={12}
        className={cn(floatingSurfaceClassName, floatingSurfaceMotionClassName, "min-w-40 rounded-control p-1 [&_[role=menuitem]]:py-1.5 [@media(pointer:coarse)]:[&_[role=menuitem]]:min-h-11")}
        onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); }}
        onClick={(event) => event.stopPropagation()}
        onInteractOutside={() => { interactedOutside.current = true; }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (!interactedOutside.current) link.current?.focus();
        }}>
        {openPreview ? <Menu.Item className={itemClassName} onSelect={() => openPreview(href)}>{t("webPreview.open")}</Menu.Item> : null}
        <Menu.Item asChild className={itemClassName}>
          <a href={href} target="_blank" rel="noreferrer noopener">{t("webPreview.external")}</a>
        </Menu.Item>
        <Menu.Item className={itemClassName} onSelect={(event) => { event.preventDefault(); void copy(); }}>{t("webPreview.copy")}</Menu.Item>
        {feedback === "copyFailed" ? <div role="status" className="max-w-64 px-2.5 py-1.5 text-xs text-muted-foreground">{t("webPreview.copyFailed")}</div> : null}
      </Menu.Content>
    </Menu.Portal>
  </Menu.Root>;
}
