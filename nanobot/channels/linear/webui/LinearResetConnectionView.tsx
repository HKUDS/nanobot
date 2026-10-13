import { useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { channelFieldInputId } from "@/components/settings/channels/CredentialForm";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";


export function LinearResetConnectionView({ disabled, onReset }: {
  disabled: boolean;
  onReset: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "linear");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const reset = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await onReset();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return <AlertDialog open={open} onOpenChange={value => {
    if (inFlight.current) return;
    setOpen(value);
    setError(null);
  }}>
    <div className="mt-4 border-t border-border/60 pt-3">
        <Button ref={triggerRef} type="button" variant="ghost" size="sm" disabled={disabled || busy}
          onClick={() => { setError(null); setOpen(true); }}
          className="h-8 rounded-full text-[12px] text-muted-foreground hover:text-destructive">
          {tx("custom.resetConnection", "Reset Linear connection")}
        </Button>
    </div>
    <AlertDialogContent className="max-w-md gap-5" onEscapeKeyDown={event => { if (inFlight.current) event.preventDefault(); }}
      onCloseAutoFocus={event => {
        event.preventDefault();
        if (triggerRef.current && !triggerRef.current.disabled) triggerRef.current.focus();
        else document.getElementById(channelFieldInputId("channels.linear.publicBaseUrl"))?.focus();
      }}>
      <AlertDialogHeader className="space-y-3 text-left">
        <AlertDialogTitle>{tx("custom.resetTitle", "Reset Linear?")}</AlertDialogTitle>
        <AlertDialogDescription asChild>
          <div className="space-y-4 text-sm leading-6">
            <p>{tx("custom.resetDescription", "Disconnect all workspaces linked through this app and stop the channel.")}</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-3 rounded-xl bg-muted/40 p-4 text-[13px] leading-5">
              <dt className="font-medium text-foreground">{tx("custom.resetClears", "Clears")}</dt>
              <dd>{tx("custom.resetClearsDetail", "Member access settings and this instance’s app configuration, including saved credentials.")}</dd>
              <dt className="font-medium text-foreground">{tx("custom.resetKeeps", "Keeps")}</dt>
              <dd>{tx("custom.resetKeepsDetail", "Linear app, issues, comments, chat history and pairing approvals.")}</dd>
            </dl>
          </div>
        </AlertDialogDescription>
      </AlertDialogHeader>
      {error ? <div role="alert" className="space-y-1 text-[12px] leading-5 text-destructive">
        <p>{tx("custom.resetIncomplete", "Reset is incomplete. Workspaces already removed stay removed; retry to finish the remaining steps.")}</p>
        <p>{error}</p>
      </div> : null}
      <AlertDialogFooter>
        <AlertDialogCancel className="h-9 min-w-20 rounded-full text-[13px]" disabled={busy}>{t("settings.actions.cancel", { defaultValue: "Cancel" })}</AlertDialogCancel>
        <Button type="button" variant="destructive" size="sm" className="min-w-20 rounded-full px-4 text-[13px]" disabled={busy} onClick={() => void reset()}>
          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
          {busy ? tx("custom.resetting", "Resetting…") : tx("custom.resetConfirm", "Reset")}
        </Button>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>;
}
