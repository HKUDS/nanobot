import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { registeredChannelUiContributions } from "@/channel-plugins/registry";
import { ChannelSetupSurfaceView } from "@/components/settings/channels/ChannelSetupSurfaceView";
import { channelRequirementErrors, focusFirstChannelFieldError } from "@/components/settings/channels/ChannelCredentialFields";
import { defaultChannelFieldValues } from "@/components/settings/channels/CredentialForm";
import { CHANNEL_SETUP_PANEL_CLASS_NAME, ChannelLogo, channelSetup, localizedChannelDisplayName } from "@/components/settings/channels/ChannelIdentity";
import type { ChannelValidationPayload } from "@/lib/types";
import { copyTextToClipboard } from "@/lib/clipboard";
import { channelFeatures } from "./channel-fixtures";
import { StatePicker, type ComponentExample } from "./example";
import { useGalleryTranslation } from "./i18n";

function ChannelEntryPreview({ name }: { name: string }) {
  const { t, i18n } = useTranslation();
  const { t: g } = useGalleryTranslation();
  const [mode, setMode] = useState<"setup" | "configured" | "enabled" | "checking" | "error">("setup");
  return <><StatePicker label={g("previews.channel.state")} value={mode}
    options={["setup", "configured", "enabled", "checking", "error"]} onChange={setMode} />
    <ChannelFormPreview key={mode} name={name} mode={mode} locale={i18n.resolvedLanguage ?? i18n.language} t={t} />
  </>;
}

function ChannelFormPreview({ name, mode, locale, t }: {
  name: string;
  mode: "setup" | "configured" | "enabled" | "checking" | "error";
  locale: string;
  t: ReturnType<typeof useTranslation>["t"];
}) {
  const { t: g } = useGalleryTranslation();
  const snapshot = channelFeatures[name];
  const configured = mode !== "setup";
  const [enabled, setEnabled] = useState(mode === "enabled");
  const feature = { ...snapshot, configured, enabled, ready: configured, status: enabled ? "enabled" : "not_enabled",
    configured_fields: configured ? snapshot.setup!.fields.filter((field) => field.kind === "secret").map((field) => field.key) : [],
    runtime_status: enabled ? "running" : "stopped",
    runtime_error: mode === "error" ? g("previews.channel.credentialsError") : undefined };
  const setup = channelSetup(feature, locale);
  const fields = setup.fields ?? [];
  const requirementKeys = new Set((setup.requirements ?? []).flatMap((item) => item.alternatives.flat()));
  const primaryFields = fields.filter((field) => !field.optional || requirementKeys.has(field.key));
  const advancedFields = fields.filter((field) => !primaryFields.includes(field));
  const configuredFields = new Set(feature.configured_fields);
  const savedSecretFields = fields.filter((field) => field.secret && configuredFields.has(field.key));
  const [values, setValues] = useState(() => {
    const initial = defaultChannelFieldValues(fields, feature.config_values);
    if (configured) for (const field of fields) {
      if (!field.optional && field.kind === "bool") initial[field.key] = "true";
      if (!field.secret && !field.optional && !initial[field.key]?.trim()) {
        initial[field.key] = field.inputType === "url" ? "https://chat.example.com" : `preview-${field.key.split(".").at(-1)}`;
      }
    }
    return initial;
  });
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [clearedSecrets, setClearedSecrets] = useState<Set<string>>(() => new Set());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [notice, setNotice] = useState<{ key: string } | { message: string } | null>(null);
  const [saved, setSaved] = useState(false);
  const [checked, setChecked] = useState(false);
  const advancedPanelId = useId();
  const validate = () => {
    const next = channelRequirementErrors(fields, setup.requirements ?? [], values, configuredFields, clearedSecrets,
      "settings.channels.fieldRequired");
    setErrors(next);
    if (Object.keys(next).length) {
      if (advancedFields.some((field) => next[field.key])) setAdvancedOpen(true);
      focusFirstChannelFieldError(next);
      setNotice({ key: "settings.channels.validationFailed" });
      return false;
    }
    setSaved(true);
    setNotice({ key: "settings.channels.savedSettings" });
    return true;
  };
  const validation: ChannelValidationPayload | null = checked ? {
    name, status: "connected", can_enable: true, requires_restart: false, missing_fields: [],
    checks: [{ id: "preview", label: g("previews.channel.validation"), status: "pass" }],
  } : null;
  return <aside className={CHANNEL_SETUP_PANEL_CLASS_NAME}>
    <ChannelSetupSurfaceView feature={feature} setup={setup}
      header={<div className="flex min-w-0 items-center gap-3"><ChannelLogo feature={feature} showBrandLogos={false} />
        <h3 className="sr-only">{localizedChannelDisplayName(feature, t)}</h3></div>}
      primaryFields={primaryFields} advancedFields={advancedFields} savedSecretFields={savedSecretFields}
      availablePresets={configured ? [] : setup.presets ?? []} configuredFields={configuredFields}
      fieldValues={values} visibleSecrets={visibleSecrets} clearedSecrets={clearedSecrets}
      fieldErrors={Object.fromEntries(Object.entries(errors).map(([key, message]) => [key, t(message)]))}
      actionPending={mode === "checking"} enabled={enabled} autoSaving={false} autoSaveState={saved ? "saved" : "idle"}
      advancedOpen={advancedOpen} advancedPanelId={advancedPanelId} validation={validation} validating={mode === "checking"}
      notice={notice ? "key" in notice ? t(notice.key) : notice.message : null}
      onAdvancedOpenChange={setAdvancedOpen}
      onChangeField={(key, value) => { setValues((current) => ({ ...current, [key]: value })); setErrors({}); setSaved(false); }}
      onToggleSecret={(key) => setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }))}
      onClearSecret={(key, clear) => setClearedSecrets((current) => {
        const next = new Set(current); if (clear) next.add(key); else next.delete(key); return next;
      })}
      onApplyPreset={(preset) => { setValues((current) => ({ ...current, ...preset.values })); setSaved(false); }}
      onSubmit={() => { if (validate()) setEnabled(true); }}
      onCheckConnection={() => { if (validate()) setChecked(true); }}
      onToggleEnabled={(next) => { if (!next || validate()) setEnabled(next); }}
      onCopyCommand={() => { if (setup.command) void copyTextToClipboard(setup.command).then((ok) => setNotice({ key: ok ? "settings.channels.commandCopied" : "settings.channels.commandCopyFailed" })); }}
      onNotice={(message) => setNotice(message ? { message } : null)} />
  </aside>;
}

const genericRegistrations = registeredChannelUiContributions()
  .filter(({ contribution }) => !contribution.Panel && !contribution.ConnectFlow);

export const channelExamples: ComponentExample[] = genericRegistrations.map(({ channel, webui, contribution }, index) => ({
  title: "previews.channel.title",
  titleValues: { channel: contribution.presentation.displayName },
  files: [`nanobot/channels/${channel}/${webui}`, ...(index === 0 ? ["webui/src/components/settings/channels/ChannelSetupSurfaceView.tsx"] : [])],
  description: "previews.channel.description",
  options: "previews.channel.options",
  code: `<ChannelSetupSurfaceView feature={channelFeatures.${channel}} setup={setup} {...displayState} {...actions} />`,
  Preview: () => <ChannelEntryPreview name={channel} />,
}));

export function withChannelEntries(customExamples: ComponentExample[]): ComponentExample[] {
  const assigned = new Set(customExamples.flatMap((example) => example.files));
  return customExamples.map((example) => {
    const entries = registeredChannelUiContributions().filter(({ channel, webui }) => {
      const entry = `nanobot/channels/${channel}/${webui}`;
      const ownsMainView = example.files.some((file) => file.startsWith(`nanobot/channels/${channel}/webui/`)
        && (file.endsWith("PanelView.tsx") || file.endsWith("WhatsAppConnectFlowView.tsx")));
      if (!ownsMainView || assigned.has(entry)) return false;
      assigned.add(entry);
      return true;
    }).map(({ channel, webui }) => `nanobot/channels/${channel}/${webui}`);
    return { ...example, files: [...example.files, ...entries] };
  });
}
