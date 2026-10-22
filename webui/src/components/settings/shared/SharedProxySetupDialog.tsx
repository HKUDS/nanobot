import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingsHint } from "@/components/settings/shared/SettingsHint";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SharedProxyEditor } from "@/components/settings/shared/SharedProxyEditor";

export function SharedProxySetupDialog({ onClose, onSave, busy }: {
  busy: boolean;
  onClose: () => void;
  onSave: (address: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [address, setAddress] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const origin = useRef(document.activeElement?.closest("[data-proxy-control]") ?? null);
  const title = t("settings.runtimeConfig.fields.network_proxy.label");
  useEffect(() => { if (error && !saving) input.current?.focus(); }, [error, saving]);
  const save = async () => {
    if (saving || busy || !address.trim()) return;
    setSaving(true);
    setError("");
    try {
      await onSave(address);
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !saving) onClose(); }}>
      <DialogContent className="max-w-sm" showCloseButton={!saving}
        onOpenAutoFocus={(event) => { event.preventDefault(); input.current?.focus(); }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          const row = origin.current;
          const target = row?.querySelector<HTMLElement>('[role="switch"]') ?? row?.querySelector<HTMLElement>("button:last-child");
          target?.focus();
        }}
        onEscapeKeyDown={(event) => { if (saving) event.preventDefault(); }}
        onPointerDownOutside={(event) => { if (saving) event.preventDefault(); }}>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <DialogHeader>
            <DialogTitle className="pr-6 text-base">
              <SettingsHint description={t("settings.runtimeConfig.fields.network_proxy.help")}>{title}</SettingsHint>
            </DialogTitle>
            <DialogDescription>{t("settings.network.sharedProxyScope")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <SharedProxyEditor value={address} inputRef={input} disabled={saving} stackCredentials
              addressProps={{ "aria-invalid": Boolean(error), "aria-describedby": error ? "shared-proxy-setup-error" : undefined }}
              onChange={(next) => { setAddress(next); setError(""); }} />
            {error ? <p id="shared-proxy-setup-error" role="alert" className="break-words text-[13px] text-destructive">{error}</p> : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={saving} onClick={onClose}>{t("settings.actions.cancel")}</Button>
            <Button type="submit" disabled={saving || busy || !address.trim()}>{saving ? t("settings.actions.saving") : t("settings.actions.save")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
