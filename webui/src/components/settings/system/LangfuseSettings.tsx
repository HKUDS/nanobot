import { useId, useRef, useState } from "react";
import { ChevronDown, Eye, EyeOff, Loader2, SquarePen, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { RestartRequiredNotice, SettingsGroup, SettingsRow, SettingsSectionTitle } from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { DisclosureContent } from "@/components/ui/disclosure";
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
    <HoverHint content={t("settings.observability.references")}>
      <label tabIndex={0} htmlFor={id} className="cursor-help text-[13px] font-medium">{label}</label>
    </HoverHint>
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
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const latestDraft = useRef(draft);
  latestDraft.current = draft;
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
  const incomplete = !draft.baseUrl.trim() || !hasPublicKey || !hasSecretKey;
  const cannotEnable = !feature?.installed || incomplete;
  const installing = action === "install:langfuse";
  const stale = probe !== null && probe.draft !== draft;
  const test = async () => {
    setTesting(true);
    setProbe(null);
    try {
      const result = await testObservabilitySettings(client, draft);
      setProbe({ draft, result });
      if (latestDraft.current === draft && !result.ok && ["invalid_url", "blocked_url", "unreachable", "timeout"].includes(result.error)) {
        setAdvancedOpen(true);
      }
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
          : code === "langfuse_support_required" ? "installOnHost" : "saveFailed";
      setSaveError(t(`settings.observability.${key}`));
      if (code === "langfuse_invalid_url") setAdvancedOpen(true);
    } finally {
      setSaving(false);
    }
  };
  return <>
    <DialogHeader className="text-left">
      <DialogTitle className="pr-6 text-base">Langfuse</DialogTitle>
    </DialogHeader>
    <fieldset disabled={saving} className="min-w-0 space-y-4">
      <div className="space-y-1.5">
        <div className="flex min-h-9 items-center justify-between gap-4">
          <HoverHint content={`${t("settings.observability.uploadWarning")} ${t("settings.observability.scope")} ${t("settings.observability.restartHelp")}`}>
            <label tabIndex={0} htmlFor={`${id}-enabled`} className="cursor-help text-[13px] font-medium">{t("settings.observability.enable")}</label>
          </HoverHint>
          <div className="flex items-center gap-3">
            {loading ? <Loader2 role="status" aria-label={t("settings.values.checking")} className="h-3.5 w-3.5 animate-spin text-muted-foreground" /> : null}
            <ToggleButton id={`${id}-enabled`} checked={draft.enabled} disabled={saving}
              label={t("settings.observability.enable")} onChange={(enabled) => {
                update({ enabled });
                if (enabled && !draft.baseUrl.trim()) setAdvancedOpen(true);
              }} />
          </div>
        </div>
        {draft.enabled ? <p className="text-[12px] leading-5 text-muted-foreground">{t("settings.observability.uploadWarning")}</p> : null}
        {settings.requires_restart ? <p role="status" className="text-[12px] leading-5 text-muted-foreground">
          {t(settings.active_enabled ? "settings.observability.runningEnabled" : "settings.observability.runningDisabled")}
          {" · "}{t("settings.status.savedRestartApply")}
        </p> : null}
      </div>
      {!loading && !feature?.installed ? (
        feature?.install_supported ? <Button type="button" variant="outline" size="sm"
          disabled={action !== null} onClick={onInstallSupport}>
          {installing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          {t(installing ? "settings.capabilities.installing" : "settings.observability.install")}
        </Button> : <p className="text-[12px] text-muted-foreground">{t("settings.observability.installOnHost")}</p>
      ) : null}
      {installError ? <p role="alert" className="text-[12px] text-destructive">{installError}</p> : null}
      <CredentialField label={t("settings.observability.publicKey")} stored={Boolean(settings.public_key_hint)}
        value={draft.publicKey} onChange={(publicKey) => update({ publicKey })} />
      <CredentialField label={t("settings.observability.secretKey")} stored={Boolean(settings.secret_key_hint)}
        value={draft.secretKey} onChange={(secretKey) => update({ secretKey })} />
      <div>
        <button type="button" aria-expanded={advancedOpen} aria-controls={`${id}-advanced`}
          onClick={() => setAdvancedOpen((open) => !open)}
          className="flex min-h-10 w-full items-center justify-between rounded-control text-[13px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {t("settings.runtimeConfig.advancedOptions")}
          <ChevronDown aria-hidden className={`h-3.5 w-3.5 transition-transform motion-reduce:transition-none ${advancedOpen ? "rotate-180" : ""}`} />
        </button>
        <DisclosureContent open={advancedOpen} id={`${id}-advanced`} className="space-y-3 pt-2">
          <div className="space-y-1.5">
            <HoverHint content={`${t("settings.observability.baseUrlHelp")} ${t("settings.observability.references")}`}>
              <label tabIndex={0} htmlFor={`${id}-url`} className="cursor-help text-[13px] font-medium">{t("settings.observability.baseUrl")}</label>
            </HoverHint>
            <Input id={`${id}-url`} type="text" value={draft.baseUrl} spellCheck={false} autoComplete="off"
              placeholder="https://cloud.langfuse.com"
              className="h-9 rounded-control text-[13px]" onChange={(event) => update({ baseUrl: event.target.value })} />
          </div>
          {settings.source === "environment" || settings.uses_environment ? <HoverHint content={t("settings.observability.fromEnvironment")}>
            <p tabIndex={0} className="w-fit cursor-help text-[12px] text-muted-foreground">{t("settings.observability.usesEnvironment")}</p>
          </HoverHint> : null}
        </DisclosureContent>
      </div>
    </fieldset>
    {draft.enabled && feature?.installed && incomplete ? <p className="text-[12px] text-destructive">{t("settings.observability.enableRequirements")}</p> : null}
    {probe ? <p role="status" className={`text-[12px] ${stale || probe.result?.ok ? "text-muted-foreground" : "text-destructive"}`}>
      {stale ? t("settings.observability.testStale") : probe.result === null
        ? t("settings.observability.testFailed") : probe.result.ok
          ? t("settings.observability.testSuccess") : t(`settings.observability.errors.${probe.result.error}`)}
    </p> : null}
    {saveError ? <p role="alert" className="text-[13px] text-destructive">{saveError}</p> : null}
    <DialogFooter className="sm:justify-between">
      <HoverHint content={t("settings.observability.testHelp")}>
        <Button type="button" variant="outline" disabled={testing || saving || incomplete} onClick={() => void test()}>
          {testing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          {t(testing ? "settings.observability.testing" : "settings.observability.test")}
        </Button>
      </HoverHint>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" disabled={saving} onClick={onClose}>{t("settings.actions.cancel")}</Button>
        <HoverHint content={t("settings.observability.restartHelp")}>
          <Button type="button" disabled={saving || testing || (draft.enabled && cannotEnable)} onClick={() => void save()}>
            {t(saving ? "settings.actions.saving" : "settings.actions.save")}
          </Button>
        </HoverHint>
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
            <span className="text-[12px] text-muted-foreground">
              {t(settings.active_enabled ? "settings.values.enabled" : "settings.values.disabled")}
            </span>
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
      <DialogContent aria-describedby={undefined} className="max-w-md" showCloseButton={!saving}
        onEscapeKeyDown={(event) => { if (saving) event.preventDefault(); }}
        onPointerDownOutside={(event) => { if (saving) event.preventDefault(); }}>
        {open ? <LangfuseForm {...props} saving={saving} setSaving={setSaving} onClose={() => setOpen(false)} /> : null}
      </DialogContent>
    </Dialog>
    {settings.requires_restart ? <div className="mt-2"><RestartRequiredNotice message={t("settings.status.savedRestartApply")} /></div> : null}
  </section>;
}
