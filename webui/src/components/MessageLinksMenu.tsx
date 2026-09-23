import { useContext, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { ArrowLeft, ChevronRight, Link2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { WebPreviewContext } from "@/components/WebLink";
import { floatingItemClassName, floatingItemFocusClassName } from "@/components/ui/floating-surface";
import { copyTextToClipboard } from "@/lib/clipboard";
import { parseWebLink } from "@/lib/web-preview";

interface MessageWebLink { href: string; title: string }

/** Read only links actually rendered in this message, not code samples or file references. */
export function useMessageWebLinks(root: RefObject<HTMLElement>, open: boolean) {
  const [links, setLinks] = useState<MessageWebLink[]>([]);
  useLayoutEffect(() => {
    const element = root.current;
    if (!open || !element) return;
    const collect = () => {
      const unique = new Map<string, MessageWebLink>();
      element.querySelectorAll<HTMLAnchorElement>("[data-assistant-selectable] a[data-web-link]").forEach((anchor) => {
        const href = anchor.getAttribute("href") ?? "";
        const url = parseWebLink(href);
        if (url && !unique.has(url.href)) {
          unique.set(url.href, { href, title: anchor.textContent?.trim() || href });
        }
      });
      setLinks(Array.from(unique.values()));
    };
    collect();
    // Markdown is lazy-loaded; collect again when its real links appear/change.
    const observer = new MutationObserver(collect);
    observer.observe(element, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["href"] });
    return () => observer.disconnect();
  }, [root, open]);
  return links;
}

const itemClassName = `${floatingItemClassName} ${floatingItemFocusClassName} w-full min-h-11 text-start hover:bg-muted/70`;

/** A drill-in inside the message's action surface, not another floating layer. */
export function MessageLinksMenu({ links, onBack, onClose, expanded = false }: {
  links: MessageWebLink[];
  onBack: () => void;
  onClose: () => void;
  expanded?: boolean;
}) {
  const { t } = useTranslation();
  const openPreview = useContext(WebPreviewContext);
  const [selected, setSelected] = useState<string | null>(links.length === 1 ? links[0].href : null);
  const active = links.find((link) => link.href === selected);
  const backRef = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => { backRef.current?.focus({ preventScroll: true }); }, [selected]);
  return <div className={expanded ? "w-full" : "w-60 max-w-full"}>
    <button ref={backRef} type="button" className={itemClassName} aria-label={t("webPreview.back")}
      onClick={() => active && links.length > 1 ? setSelected(null) : onBack()}>
      <ArrowLeft aria-hidden /><span>{t("webPreview.viewLinks")}</span>
    </button>
    {active ? <MessageLinkActions key={active.href} link={active} onClose={onClose}
      onPreview={openPreview ? () => { onClose(); openPreview(active.href); } : undefined} />
      : <div className="border-t border-border/45 pt-1">
        {links.map((link) => <button type="button" key={link.href} className={itemClassName} onClick={() => setSelected(link.href)}>
          <Link2 className="text-muted-foreground" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{link.title}</span><ChevronRight className="text-muted-foreground" aria-hidden />
        </button>)}
      </div>}
  </div>;
}

function MessageLinkActions({ link, onClose, onPreview }: {
  link: MessageWebLink;
  onClose: () => void;
  onPreview?: () => void;
}) {
  const { t } = useTranslation();
  const [feedback, setFeedback] = useState<"copied" | "copyFailed" | null>(null);
  const mounted = useRef(false);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const copy = async () => {
    const success = await copyTextToClipboard(link.href);
    if (mounted.current) setFeedback(success ? "copied" : "copyFailed");
  };
  return <div className="border-t border-border/45 pt-1">
    <p className="max-h-24 overflow-y-auto px-2.5 py-2 text-xs text-muted-foreground [overflow-wrap:anywhere]" dir="auto">{link.href}</p>
    {onPreview ? <button type="button" className={itemClassName} onClick={onPreview}>{t("webPreview.open")}</button> : null}
    <a className={itemClassName} href={link.href} target="_blank" rel="noreferrer noopener" onClick={onClose}>{t("webPreview.external")}</a>
    <button type="button" className={itemClassName} onClick={() => { void copy(); }}>{t("webPreview.copy")}</button>
    {feedback ? <p role="status" className="px-2.5 py-1.5 text-xs text-muted-foreground">{t(`webPreview.${feedback}`)}</p> : null}
  </div>;
}
