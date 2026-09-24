import { useEffect, useRef, useState } from "react";
import { ExternalLink, Github } from "lucide-react";
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
      className={fullWidth ? undefined : "settings-list-row flex select-none items-center gap-3 text-[14px] settings-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"}
      onClick={dismiss} onAuxClick={(event) => { if (event.button === 1) dismiss(); }}>
      <Github className={fullWidth ? "mr-2 h-4 w-4" : "h-4 w-4 text-muted-foreground"} aria-hidden />
      <span className={fullWidth ? undefined : "flex-1"}>
        {t(fullWidth ? "starPrompt.action" : "settings.about.sourceCode")}
      </span>
      <ExternalLink className={fullWidth ? "ml-2 h-3.5 w-3.5" : "h-3.5 w-3.5 text-muted-foreground"} aria-hidden />
    </a>
  );
  return (
    <>
      {fullWidth ? <Button asChild className="w-full">{link}</Button> : link}
      {error && <p role="alert" className="text-sm text-destructive">{t("starPrompt.saveError")}</p>}
    </>
  );
}

export function StarPrompt({ ready, busy }: { ready: boolean; busy: boolean }) {
  const { client } = useClient();
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const attempted = useRef(false);
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const previousFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!ready || attempted.current) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (client.status !== "open") return;
      attempted.current = true;
      // Only invite on entry, never after a running conversation finishes.
      if (busyRef.current || document.visibilityState !== "visible"
        || document.querySelector('[role="dialog"], [role="alertdialog"]')) return;
      previousFocus.current = document.activeElement instanceof HTMLElement
        ? document.activeElement : null;
      void starPromptAction(client, "claim").then(({ show }) => {
        if (!cancelled && show && !busyRef.current && document.visibilityState === "visible"
          && !document.querySelector('[role="dialog"], [role="alertdialog"]')) setOpen(true);
      }).catch(() => { /* Optional invitations stay hidden when storage is unavailable. */ });
    }, 2000);
    return () => { cancelled = true; window.clearTimeout(timer); };
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
      <DialogContent className="max-w-sm" onCloseAutoFocus={(event) => {
        event.preventDefault();
        previousFocus.current?.focus({ preventScroll: true });
      }}>
        <DialogTitle>{t("starPrompt.title")}</DialogTitle>
        <DialogDescription className="leading-relaxed">{t("starPrompt.description")}</DialogDescription>
        <div className="flex flex-col gap-2 pt-2">
          <StarLink fullWidth onSaved={() => setOpen(false)} />
          <Button variant="outline" onClick={() => setOpen(false)}>{t("starPrompt.later")}</Button>
          <Button variant="ghost" className="text-muted-foreground" disabled={saving}
            onClick={() => void dismissForever()}>{t("starPrompt.never")}</Button>
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{t("starPrompt.saveError")}</p>}
      </DialogContent>
    </Dialog>
  );
}
