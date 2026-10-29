import { useId, useState } from "react";
import { Eye, EyeOff, Loader2, SquarePen, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { RestartRequiredNotice, SettingsGroup, SettingsRow, SettingsSectionTitle } from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ToggleButton } from "@/components/ui/toggle-button";
import { HoverHint } from "@/components/ui/tooltip";
import { testObservabilitySettings } from "@/lib/api";
import type { NanobotFeatureInfo, ObservabilitySettingsPayload, ObservabilitySettingsUpdate, ObservabilityTestResult } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

interface LangfuseSettingsProps {
  settings: ObservabilitySettingsPayload;
  feature?: NanobotFeatureInfo;
  loading: boolean;
  action: string | null;
  installError: string | null;
  disabled?: boolean;
  onInstallSupport: () => void;
  onSave: (draft: ObservabilitySettingsUpdate) => Promise<void>;
}

function TracingStatus({ settings, inline = false }: { settings: ObservabilitySettingsPayload; inline?: boolean }) {
  const { t } = useTranslation();
  return <div className={`text-[12px] leading-5 text-muted-foreground ${inline ? "flex flex-wrap gap-x-4" : ""}`}>
    <p>{t(settings.active_enabled ? "settings.observability.runningEnabled" : "settings.observability.runningDisabled")}</p>
    <p>{t(settings.enabled ? "settings.observability.savedEnabled" : "settings.observability.savedDisabled")}</p>
  </div>;
}

function CredentialField({ label, stored, value, onChange }: {
  label: string;
  stored: boolean;
  value: string | undefined;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [editing, setEditing] = useState(!stored);
  const [visible, setVisible] = useState(false);
  const canReveal = editing && Boolean(value);
  const help = stored && value === "" ? t("settings.observability.keyCleared") : null;
  return <div className="space-y-1.5">
    <label htmlFor={id} className="text-[13px] font-medium">{label}</label>
    <div className="flex items-center gap-2">
      <div className="relative min-w-0 flex-1">
        <Input id={id} type={canReveal && visible ? "text" : "password"} value={value ?? ""}
          readOnly={!editing} autoComplete="off" spellCheck={false}
          placeholder={editing ? t("settings.observability.keyPlaceholder") : "••••••••"}
          aria-describedby={help ? `${id}-help` : undefined}
          onChange={(event) => { onChange(event.target.value); if (!event.target.value) setVisible(false); }}
          className="h-9 rounded-control pr-9 text-[13px]" />
        {canReveal ? <Button type="button" variant="ghost" size="icon"
          className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full"
          aria-label={t(visible ? "settings.observability.hideKey" : "settings.observability.showKey", { key: label })}
          onClick={() => setVisible((current) => !current)}>
          {visible ? <EyeOff className="h-3.5 w-3.5" aria-hidden /> : <Eye className="h-3.5 w-3.5" aria-hidden />}
        </Button> : null}
      </div>
      {!editing ? <Button type="button" variant="outline" size="sm" onClick={() => setEditing(true)}
        aria-label={t("settings.observability.replaceKey", { key: label })}>
        {t("settings.observability.replace")}
      </Button> : null}
      {stored || value ? <HoverHint content={t("settings.observability.clearKey", { key: label })}>
        <Button type="button" variant="ghost" size="icon" className="h-9 w-9 shrink-0 rounded-full"
          aria-label={t("settings.observability.clearKey", { key: label })}
          onClick={() => { onChange(""); setEditing(true); setVisible(false); }}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </HoverHint> : null}
    </div>
    {help ? <p id={`${id}-help`} className="text-[12px] text-muted-foreground">{help}</p> : null}
  </div>;
}

function LangfuseForm({ settings, feature, loading, action, installError, onInstallSupport, onSave, saving, setSaving, onClose }: LangfuseSettingsProps & {
  saving: boolean;
  setSaving: (saving: boolean) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { client } = useClient();
  const id = useId();
  const [draft, setDraft] = useState<ObservabilitySettingsUpdate>(() => ({
    enabled: settings.enabled ?? false,
    baseUrl: settings.base_url,
  }));
  const [saveError, setSaveError] = useState("");
  const [testing, setTesting] = useState(false);
  const [probe, setProbe] = useState<{
    draft: ObservabilitySettingsUpdate;
    result: ObservabilityTestResult | null;
  } | null>(null);
  const update = (change: Partial<ObservabilitySettingsUpdate>) => {
    setDraft((current) => ({ ...current, ...change }));
    setSaveError("");
  };
  const hasPublicKey = draft.publicKey === undefined ? Boolean(settings.public_key_hint) : Boolean(draft.publicKey.trim());
  const hasSecretKey = draft.secretKey === undefined ? Boolean(settings.secret_key_hint) : Boolean(draft.secretKey.trim());
  const cannotEnable = !feature?.installed || !draft.baseUrl.trim() || !hasPublicKey || !hasSecretKey;
  const installing = action === "install:langfuse";
  const stale = probe !== null && probe.draft !== draft;
  const test = async () => {
    setTesting(true);
    setProbe(null);
    try {
      const result = await testObservabilitySettings(client, draft);
      setProbe({ draft, result });
    } catch {
      setProbe({ draft, result: null });
    } finally {
      setTesting(false);
    }
  };
  const save = async () => {
    if (saving || testing || (draft.enabled && cannotEnable)) return;
    setSaving(true);
    setSaveError("");
    try {
      await onSave(draft);
      onClose();
    } catch (error) {
      const code = error instanceof Error ? error.message : "";
      const key = code === "langfuse_missing_credentials" ? "errors.missing_credentials"
        : code === "langfuse_invalid_url" ? "errors.invalid_url"
          : code === "langfuse_support_required" ? "enableRequirements" : "saveFailed";
      setSaveError(t(`settings.observability.${key}`));
    } finally {
      setSaving(false);
    }
  };
  return <>
    <DialogHeader>
      <DialogTitle className="pr-6 text-base">{t("settings.observability.configure")}</DialogTitle>
      <DialogDescription>{t("settings.observability.uploadWarning")}</DialogDescription>
    </DialogHeader>
    <TracingStatus settings={settings} inline />
    {settings.requires_restart ? <RestartRequiredNotice message={t("settings.status.savedRestartApply")} /> : null}
    <fieldset disabled={saving} className="min-w-0 space-y-3">
      <div className="flex items-center justify-between gap-4">
        <div>
          <HoverHint content={t("settings.observability.scope")}>
            <label tabIndex={0} htmlFor={`${id}-enabled`} className="cursor-help text-[13px] font-medium">{t("settings.observability.enable")}</label>
          </HoverHint>
        </div>
        <ToggleButton id={`${id}-enabled`} checked={draft.enabled} disabled={saving}
          label={t("settings.observability.enable")} onChange={(enabled) => update({ enabled })} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-muted-foreground">
        <span>{t(loading ? "settings.values.checking" : feature?.installed
          ? "settings.observability.installed" : "settings.observability.notInstalled")}</span>
        {!loading && !feature?.installed && feature?.install_supported ? <Button type="button" variant="outline" size="sm"
          disabled={action !== null} onClick={onInstallSupport}>
          {installing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          {t(installing ? "settings.capabilities.installing" : "settings.observability.install")}
        </Button> : null}
      </div>
      {!loading && !feature?.installed && !feature?.install_supported ?
        <p className="text-[12px] text-muted-foreground">{t("settings.observability.installOnHost")}</p> : null}
      {installError ? <p role="alert" className="text-[12px] text-destructive">{installError}</p> : null}
      <div className="space-y-1.5">
        <HoverHint content={`${t("settings.observability.baseUrlHelp")} ${t("settings.observability.references")}`}>
          <label tabIndex={0} htmlFor={`${id}-url`} className="cursor-help text-[13px] font-medium">{t("settings.observability.baseUrl")}</label>
        </HoverHint>
        <Input id={`${id}-url`} type="text" value={draft.baseUrl} spellCheck={false} autoComplete="off"
          placeholder="https://cloud.langfuse.com"
          className="h-9 rounded-control text-[13px]" onChange={(event) => update({ baseUrl: event.target.value })} />
      </div>
      <CredentialField label={t("settings.observability.publicKey")} stored={Boolean(settings.public_key_hint)}
        value={draft.publicKey} onChange={(publicKey) => update({ publicKey })} />
      <CredentialField label={t("settings.observability.secretKey")} stored={Boolean(settings.secret_key_hint)}
        value={draft.secretKey} onChange={(secretKey) => update({ secretKey })} />
      <div className="space-y-1 text-[12px] text-muted-foreground">
        {settings.source === "environment" || settings.uses_environment ? <p>
          {t(settings.source === "environment" ? "settings.observability.fromEnvironment" : "settings.observability.usesEnvironment")}
        </p> : null}
      </div>
    </fieldset>
    {draft.enabled && cannotEnable ? <p className="text-[12px] text-destructive">{t("settings.observability.enableRequirements")}</p> : null}
    <div className="space-y-1">
      {probe ? <p role="status" className={`text-[12px] ${stale || probe.result?.ok ? "text-muted-foreground" : "text-destructive"}`}>
        {stale ? t("settings.observability.testStale") : probe.result === null
          ? t("settings.observability.testFailed") : probe.result.ok
            ? t("settings.observability.testSuccess") : t(`settings.observability.errors.${probe.result.error}`)}
      </p> : null}
    </div>
    <p className="text-[12px] text-muted-foreground">{t("settings.observability.restartHelp")}</p>
    {saveError ? <p role="alert" className="text-[13px] text-destructive">{saveError}</p> : null}
    <DialogFooter className="sm:justify-between">
      <HoverHint content={t("settings.observability.testHelp")}>
        <Button type="button" variant="outline" disabled={testing || saving} onClick={() => void test()}>
          {testing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          {t(testing ? "settings.observability.testing" : "settings.observability.test")}
        </Button>
      </HoverHint>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" disabled={saving} onClick={onClose}>{t("settings.actions.cancel")}</Button>
        <Button type="button" disabled={saving || testing || (draft.enabled && cannotEnable)} onClick={() => void save()}>
          {t(saving ? "settings.actions.saving" : "settings.actions.save")}
        </Button>
      </div>
    </DialogFooter>
  </>;
}

export function LangfuseSettings(props: LangfuseSettingsProps) {
  const { settings, disabled } = props;
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  return <section>
    <SettingsSectionTitle>{t("settings.observability.title")}</SettingsSectionTitle>
    <Dialog open={open} onOpenChange={(next) => { if (!saving) setOpen(next); }}>
      <SettingsGroup>
        <SettingsRow title="Langfuse">
          <div className="flex items-center justify-end gap-3">
            <div className="text-right"><TracingStatus settings={settings} /></div>
            <HoverHint content={t("settings.observability.configure")}>
              <DialogTrigger asChild>
                <Button type="button" variant="ghost" size="icon" disabled={disabled}
                  aria-label={t("settings.observability.configure")} className="h-9 w-9 shrink-0 rounded-full text-muted-foreground">
                  <SquarePen className="h-4 w-4" aria-hidden />
                </Button>
              </DialogTrigger>
            </HoverHint>
          </div>
        </SettingsRow>
      </SettingsGroup>
      <DialogContent className="max-w-xl gap-3" showCloseButton={!saving}
        onEscapeKeyDown={(event) => { if (saving) event.preventDefault(); }}
        onPointerDownOutside={(event) => { if (saving) event.preventDefault(); }}>
        {open ? <LangfuseForm {...props} saving={saving} setSaving={setSaving} onClose={() => setOpen(false)} /> : null}
      </DialogContent>
    </Dialog>
    {settings.requires_restart ? <div className="mt-2"><RestartRequiredNotice message={t("settings.status.savedRestartApply")} /></div> : null}
  </section>;
}
