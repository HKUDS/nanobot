import { useEffect, useRef, useState } from "react";
import { ExternalLink, Sparkle, Star, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import starInvitation from "@/assets/star-invitation.webp";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { starPromptAction } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

import "./StarPrompt.css";

const REPOSITORY_URL = "https://github.com/HKUDS/nanobot";
const actionClassName = "h-full min-h-[46px] min-w-0 !whitespace-normal px-3 py-2.5 text-center text-[15px] font-medium max-[480px]:text-sm";

export function StarLink({ onSaved, fullWidth = false }: {
  onSaved?: () => void;
  fullWidth?: boolean;
}) {
  const { client } = useClient();
  const { t } = useTranslation();
  const [error, setError] = useState(false);
  const dismiss = () => {
    setError(false);
    void starPromptAction(client, "dismiss").then(onSaved).catch(() => setError(true));
  };
  const link = (
    <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer"
      className={fullWidth ? undefined : "inline-flex min-h-10 items-center justify-center gap-2 rounded-control px-2 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"}
      onClick={dismiss} onAuxClick={(event) => { if (event.button === 1) dismiss(); }}>
      {!fullWidth && <Star className="h-4 w-4 shrink-0" aria-hidden />}
      <span className="min-w-0">
        {t(fullWidth ? "starPrompt.action" : "starPrompt.footerAction")}
      </span>
      {fullWidth ? (
        <span className="star-prompt-decoration" aria-hidden="true">
          <Star className="star-prompt-star" size={23} strokeWidth={1.5} fill="currentColor" />
          <Sparkle className="star-prompt-sparkle star-prompt-sparkle-first" size={10} strokeWidth={1.5} fill="currentColor" />
          <Sparkle className="star-prompt-sparkle star-prompt-sparkle-second" size={7} strokeWidth={1.5} fill="currentColor" />
        </span>
      ) : <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />}
    </a>
  );
  return (
    <>
      {fullWidth ? <Button asChild className={`star-prompt-action relative isolate w-full overflow-visible ${actionClassName}`}>{link}</Button> : link}
      {error && <p role="alert" className="text-sm text-destructive">{t("starPrompt.saveError")}</p>}
    </>
  );
}

export function StarPrompt({ ready }: { ready: boolean }) {
  const { client } = useClient();
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const attempted = useRef(false);
  const interacted = useRef(false);
  const previousFocus = useRef<HTMLElement | null>(null);
  const titleRef = useRef<HTMLHeadingElement | null>(null);

  useEffect(() => {
    const cancel = () => { interacted.current = true; };
    const events = ["pointerdown", "keydown", "input", "wheel"] as const;
    for (const event of events) document.addEventListener(event, cancel, { capture: true, passive: true });
    return () => {
      for (const event of events) document.removeEventListener(event, cancel, true);
    };
  }, []);

  useEffect(() => {
    if (!ready || attempted.current) return;
    let cancelled = false;
    const unsubscribe = client.onStatus((status) => {
      if (status !== "open" || attempted.current) return;
      attempted.current = true;
      if (interacted.current || document.visibilityState !== "visible"
        || document.querySelector('[role="dialog"], [role="alertdialog"]')) return;
      void starPromptAction(client, "claim").then(({ show }) => {
        if (cancelled || !show || interacted.current || document.visibilityState !== "visible"
          || document.querySelector('[role="dialog"], [role="alertdialog"]')) return;
        previousFocus.current = document.activeElement instanceof HTMLElement
          ? document.activeElement : null;
        setOpen(true);
      }).catch(() => { /* Optional invitations stay hidden when storage is unavailable. */ });
    });
    return () => { cancelled = true; unsubscribe(); };
  }, [client, ready]);

  const dismissForever = async () => {
    setSaving(true);
    setError(false);
    try {
      await starPromptAction(client, "dismiss");
      setOpen(false);
    } catch {
      setError(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent showCloseButton={false}
        className="flex max-h-[calc(100dvh-32px)] max-w-[520px] flex-col gap-0 overflow-y-auto overscroll-contain p-5 pb-2.5 outline-none max-[480px]:p-4 max-[480px]:pb-2"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          titleRef.current?.focus({ preventScroll: true });
        }} onCloseAutoFocus={(event) => {
        event.preventDefault();
        previousFocus.current?.focus({ preventScroll: true });
      }}>
        <img src={starInvitation} alt="" width={1672} height={941} draggable={false}
          className="aspect-[1672/941] w-full shrink-0 select-none rounded-control bg-muted object-cover" />
        <DialogClose aria-label={t("common.close")}
          className="absolute right-[23px] top-[23px] grid h-11 w-11 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-white max-[480px]:right-[18px] max-[480px]:top-[18px]">
          <span className="grid h-[30px] w-[30px] place-items-center rounded-full bg-black/40 text-white backdrop-blur-sm transition-colors hover:bg-black/60 motion-reduce:transition-none">
            <X size={18} strokeWidth={1.75} aria-hidden />
          </span>
        </DialogClose>
        <div className="shrink-0 px-2 pt-[27px] text-left max-[480px]:px-1 max-[480px]:pt-[23px]">
          <DialogTitle ref={titleRef} tabIndex={-1}
            className="text-[26px] font-semibold leading-[1.4] tracking-[-0.035em] outline-none [overflow-wrap:anywhere] max-[480px]:text-[clamp(18px,5.6vw,24px)]">
            {t("starPrompt.title")}
          </DialogTitle>
          <DialogDescription className="mt-[15px] text-[15px] leading-[1.9] text-muted-foreground max-[480px]:mt-3 max-[480px]:text-[13px] max-[480px]:leading-[1.95]">
            <span className="block">{t("starPrompt.intro")}</span>{" "}
            <span className="block">{t("starPrompt.invitation")}</span>{" "}
            <span className="block">{t("starPrompt.thanks")}</span>
          </DialogDescription>
        </div>
        <div className="mt-[27px] grid shrink-0 grid-cols-2 items-stretch gap-3 px-2 max-[480px]:mt-[23px] max-[480px]:gap-2.5 max-[480px]:px-1">
          <Button variant="outline" className={actionClassName}
            onClick={() => setOpen(false)}>{t("starPrompt.later")}</Button>
          <div className="flex min-w-0 flex-col gap-2">
            <StarLink fullWidth onSaved={() => setOpen(false)} />
          </div>
        </div>
        <Button variant="ghost" className="mt-[7px] min-h-11 shrink-0 self-center !whitespace-normal px-4 text-xs font-normal text-muted-foreground" disabled={saving}
          onClick={() => void dismissForever()}>{t("starPrompt.never")}</Button>
        {error && <p role="alert" className="text-sm text-destructive">{t("starPrompt.saveError")}</p>}
      </DialogContent>
    </Dialog>
  );
}
