import { useRef, useState } from "react";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import {
  ReadOnlyRow,
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
} from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { SettingsPayload } from "@/lib/types";

export function WebuiAccessSettings({ access, canSetPassword, saving, error, onChange }: {
  access: NonNullable<SettingsPayload["webui_access"]>;
  canSetPassword: boolean;
  saving: boolean;
  error: string | null;
  onChange: (allowOtherDevices: boolean, password?: string) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmationRef = useRef<HTMLInputElement>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(false);
  const formError = validationError ?? (attempted ? error : null);
  const passwordUnavailable = access.password_required && !canSetPassword;
  const statusVisible = passwordUnavailable || access.requires_restart || Boolean(error && !passwordOpen);

  const toggleAccess = (allow: boolean) => {
    if (allow && access.password_required) {
      setPassword("");
      setConfirmation("");
      setPasswordVisible(false);
      setValidationError(null);
      setAttempted(false);
      setPasswordOpen(true);
    } else {
      void onChange(allow);
    }
  };
  const submitPassword = async (event: React.FormEvent) => {
    event.preventDefault();
    if (saving) return;
    const secret = password;
    if (secret.length < 8 || secret.length > 1024 || /[^\x21-\x7e]/.test(secret)
      || !/[a-z]/.test(secret) || !/[A-Z]/.test(secret) || !/[0-9]/.test(secret)
      || !/[^A-Za-z0-9]/.test(secret) || secret.includes("${")) {
      setValidationError(t("settings.webuiAccess.passwordInvalid"));
      passwordRef.current?.focus();
      return;
    }
    if (secret !== confirmation) {
      setValidationError(t("settings.webuiAccess.passwordMismatch"));
      confirmationRef.current?.focus();
      return;
    }
    setValidationError(null);
    setAttempted(true);
    if (await onChange(true, secret)) setPasswordOpen(false);
  };
  return (
    <section aria-label={t("settings.webuiAccess.title")}>
      <SettingsSectionTitle>{t("settings.webuiAccess.title")}</SettingsSectionTitle>
      <SettingsGroup>
        <SettingsRow
          title={t("settings.webuiAccess.allowOtherDevices")}
          description={`${t(access.can_change ? "settings.webuiAccess.description" : "settings.webuiAccess.managed")} ${t("settings.webuiAccess.networkScope")}`}
        >
          <ToggleButton
            checked={access.allow_other_devices}
            disabled={saving || !access.can_change || (!access.allow_other_devices && passwordUnavailable)}
            onChange={toggleAccess}
            label={t("settings.webuiAccess.allowOtherDevices")}
            aria-describedby={statusVisible ? "webui-access-status" : undefined}
          />
        </SettingsRow>
        <ReadOnlyRow
          title={t("settings.webuiAccess.activeHost")}
          value={access.active_host}
          description={t(access.active_allow_other_devices ? "settings.webuiAccess.networkActive" : "settings.webuiAccess.localActive")}
        />
      </SettingsGroup>
      {statusVisible ? (
        <div id="webui-access-status" className="mt-3 space-y-2 text-[13px] leading-5 text-muted-foreground">
          {passwordUnavailable ? <p>{t("settings.webuiAccess.passwordLocalOnly")}</p> : null}
          {access.requires_restart ? (
            <p role="status" className="text-foreground">
              {t(access.allow_other_devices ? "settings.webuiAccess.pendingEnable" : "settings.webuiAccess.pendingDisable")}
            </p>
          ) : null}
          {error && !passwordOpen ? <p role="alert" className="text-destructive">{error}</p> : null}
        </div>
      ) : null}
      <Dialog open={passwordOpen} onOpenChange={(open) => { if (!saving) setPasswordOpen(open); }}>
        <DialogContent
          showCloseButton={!saving}
          onOpenAutoFocus={(event) => { event.preventDefault(); passwordRef.current?.focus(); }}
        >
          <DialogHeader>
            <DialogTitle>{t("settings.webuiAccess.passwordTitle")}</DialogTitle>
            <DialogDescription>{t("settings.webuiAccess.passwordDescription")}</DialogDescription>
          </DialogHeader>
          <form onSubmit={(event) => void submitPassword(event)} className="space-y-4">
            <div>
              <label htmlFor="webui-access-password" className="mb-2 block text-sm font-medium">{t("app.auth.label")}</label>
              <div className="relative">
                <Input
                  ref={passwordRef}
                  id="webui-access-password"
                  type={passwordVisible ? "text" : "password"}
                  autoComplete="new-password"
                  value={password}
                  disabled={saving}
                  onChange={(event) => { setPassword(event.target.value); setValidationError(null); }}
                  aria-describedby={formError ? "webui-access-password-error" : undefined}
                  className="pr-11"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={saving}
                  aria-label={t(passwordVisible ? "app.auth.hidePassword" : "app.auth.showPassword")}
                  aria-controls="webui-access-password webui-access-confirmation"
                  aria-pressed={passwordVisible}
                  onClick={() => setPasswordVisible((visible) => !visible)}
                  className="absolute right-1 top-1/2 h-8 w-8 -translate-y-1/2"
                >
                  {passwordVisible ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
                </Button>
              </div>
            </div>
            <div>
              <label htmlFor="webui-access-confirmation" className="mb-2 block text-sm font-medium">{t("settings.webuiAccess.passwordConfirm")}</label>
              <Input
                ref={confirmationRef}
                id="webui-access-confirmation"
                type={passwordVisible ? "text" : "password"}
                autoComplete="new-password"
                value={confirmation}
                disabled={saving}
                onChange={(event) => { setConfirmation(event.target.value); setValidationError(null); }}
                aria-describedby={formError ? "webui-access-password-error" : undefined}
              />
            </div>
            {formError ? <p id="webui-access-password-error" role="alert" className="text-sm text-destructive">{formError}</p> : null}
            <DialogFooter>
              <Button type="button" variant="outline" disabled={saving} onClick={() => setPasswordOpen(false)}>{t("settings.actions.cancel")}</Button>
              <Button type="submit" disabled={saving}>
                {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : null}
                {t(saving ? "settings.actions.saving" : "settings.webuiAccess.passwordSubmit")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
