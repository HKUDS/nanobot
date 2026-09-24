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
  return (
    <div className="flex flex-col items-center gap-2">
      <Button asChild className={fullWidth ? "w-full" : undefined} variant={fullWidth ? "default" : "outline"}>
        <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer"
          onClick={dismiss} onAuxClick={(event) => { if (event.button === 1) dismiss(); }}>
          <Github className="mr-2 h-4 w-4" aria-hidden />
          {t("starPrompt.action")}
          <ExternalLink className="ml-2 h-3.5 w-3.5" aria-hidden />
        </a>
      </Button>
      {error && <p role="alert" className="text-sm text-destructive">{t("starPrompt.saveError")}</p>}
    </div>
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
