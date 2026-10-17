import { useEffect, useRef, useState } from "react";

import { StarLinkView, StarPromptView } from "@/components/StarPromptView";
import { starPromptAction } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

export function StarLink({ onSaved, fullWidth = false }: {
  onSaved?: () => void;
  fullWidth?: boolean;
}) {
  const { client } = useClient();
  const [error, setError] = useState(false);
  const dismiss = () => {
    setError(false);
    void starPromptAction(client, "dismiss").then(onSaved).catch(() => setError(true));
  };
  return <StarLinkView fullWidth={fullWidth} error={error} onActivate={dismiss} />;
}

export function StarPrompt({ ready }: { ready: boolean }) {
  const { client } = useClient();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const attempted = useRef(false);
  const interacted = useRef(false);
  const previousFocus = useRef<HTMLElement | null>(null);
  const [starError, setStarError] = useState(false);

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

  const openRepository = () => {
    setStarError(false);
    void starPromptAction(client, "dismiss").then(() => setOpen(false)).catch(() => setStarError(true));
  };
  return <StarPromptView open={open} saving={saving} error={error} starError={starError}
    onOpenChange={setOpen} onDismissForever={() => void dismissForever()} onStar={openRepository}
    onCloseAutoFocus={event => {
      event.preventDefault();
      previousFocus.current?.focus({ preventScroll: true });
    }} />;
}
