import { useEffect, useRef, useState } from "react";
import { ExternalLink, Star } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { starPromptAction } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

const REPOSITORY_URL = "https://github.com/HKUDS/nanobot";

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
      <ExternalLink className={fullWidth ? "ml-2 h-3.5 w-3.5 shrink-0" : "h-3.5 w-3.5 shrink-0 text-muted-foreground"} aria-hidden />
    </a>
  );
  return (
    <>
      {fullWidth ? <Button asChild className="h-full min-h-11 w-full !whitespace-normal px-3 py-2.5 text-center text-sm font-medium">{link}</Button> : link}
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
      <DialogContent className="max-w-[440px] gap-0 p-6 text-center outline-none"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          titleRef.current?.focus({ preventScroll: true });
        }} onCloseAutoFocus={(event) => {
        event.preventDefault();
        previousFocus.current?.focus({ preventScroll: true });
      }}>
        <img src="/brand/nanobot_mark.svg" alt="" className="mx-auto mb-4 h-10 w-10 select-none" draggable={false} />
        <DialogTitle ref={titleRef} tabIndex={-1}
          className="text-xl font-semibold leading-tight tracking-normal outline-none">
          {t("starPrompt.title")}
        </DialogTitle>
        <DialogDescription className="mt-3 text-sm leading-6 text-muted-foreground">
          {t("starPrompt.description")}
        </DialogDescription>
        <div className="mt-6 grid grid-cols-2 items-stretch gap-2">
          <Button variant="ghost" className="h-full min-h-11 !whitespace-normal bg-muted/70 px-3 py-2.5 text-sm font-medium settings-hover"
            onClick={() => setOpen(false)}>{t("starPrompt.later")}</Button>
          <div className="flex flex-col gap-2">
            <StarLink fullWidth onSaved={() => setOpen(false)} />
          </div>
        </div>
        <Button variant="ghost" className="mx-auto mt-3 h-9 px-3 text-xs font-normal text-muted-foreground" disabled={saving}
          onClick={() => void dismissForever()}>{t("starPrompt.never")}</Button>
        {error && <p role="alert" className="text-sm text-destructive">{t("starPrompt.saveError")}</p>}
      </DialogContent>
    </Dialog>
  );
}
