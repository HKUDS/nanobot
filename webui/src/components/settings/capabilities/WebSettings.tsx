import { useAutoSave } from "@/components/settings/shared/useAutoSave";
import { SettingsAdvancedOptions } from "@/components/settings/shared/SettingsFeature";
import type { Dispatch, SetStateAction } from "react";
import { Eye, EyeOff, Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ProviderPicker } from "@/components/settings/shared/ModelControls";
import {
  CapabilityInstallNotice,
  NumberInput,
  RestartSettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
  StatusPill,
} from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  NanobotFeatureInfo,
  SettingsPayload,
  WebSearchSettingsUpdate,
} from "@/lib/types";

export const DEFAULT_WEB_SEARCH_FORM: WebSearchSettingsUpdate = {
  provider: "duckduckgo",
  apiKey: "",
  baseUrl: "",
  maxResults: 5,
  timeout: 30,
  useJinaReader: true,
};

export function webSearchFormFromPayload(
  payload: SettingsPayload,
  previous?: WebSearchSettingsUpdate,
): WebSearchSettingsUpdate {
  return {
    provider: payload.web_search.provider,
    apiKey: previous?.provider === payload.web_search.provider ? previous.apiKey ?? "" : "",
    baseUrl: payload.web_search.base_url ?? "",
    maxResults: payload.web_search.max_results,
    timeout: payload.web_search.timeout,
    useJinaReader: payload.web.fetch.use_jina_reader,
  };
}

type WebSearchProviderOption = SettingsPayload["web_search"]["providers"][number];

export function webSearchProviderAcceptsApiKey(provider?: WebSearchProviderOption): boolean {
  return provider?.credential === "api_key" || provider?.credential === "optional_api_key";
}

export function webSearchProviderRequiresApiKey(provider?: WebSearchProviderOption): boolean {
  return provider?.credential === "api_key";
}

export function webSearchDraftState(settings: SettingsPayload, form: WebSearchSettingsUpdate) {
  const provider = settings.web_search.providers.find((row) => row.name === form.provider);
  const apiKey = form.apiKey?.trim() ?? "";
  const baseUrl = form.baseUrl?.trim() ?? "";
  const hasExistingSecret = webSearchProviderAcceptsApiKey(provider) &&
    form.provider === settings.web_search.provider && Boolean(settings.web_search.api_key_hint);
  const jinaReaderDirty = (form.useJinaReader ?? settings.web.fetch.use_jina_reader) !== settings.web.fetch.use_jina_reader;
  return {
    hasExistingSecret,
    jinaReaderDirty,
    dirty: form.provider !== settings.web_search.provider || apiKey.length > 0 ||
      baseUrl !== (settings.web_search.base_url ?? "") || form.maxResults !== settings.web_search.max_results ||
      form.timeout !== settings.web_search.timeout || jinaReaderDirty,
    missingCredential: webSearchProviderRequiresApiKey(provider) ? !apiKey && !hasExistingSecret
      : provider?.credential === "base_url" ? !baseUrl : false,
  };
}

export function WebSettings({
  embedded = false,
  error,
  enabled = true,
  settings,
  form,
  keyVisible,
  keyEditing,
  saving,
  onChangeForm,
  onChangeProvider,
  onToggleKey,
  onToggleKeyEditing,
  onReset,
  onSave,
  showBrandLogos,
  onRestart,
  isRestarting,
  requiresRestartPending,
  olostepFeature,
  olostepInstalling,
  capabilityError,
}: {
  embedded?: boolean;
  error?: string;
  enabled?: boolean;
  settings: SettingsPayload;
  form: WebSearchSettingsUpdate;
  keyVisible: boolean;
  keyEditing: boolean;
  saving: boolean;
  onChangeForm: Dispatch<SetStateAction<WebSearchSettingsUpdate>>;
  onChangeProvider: (provider: string) => void;
  onToggleKey: () => void;
  onToggleKeyEditing: () => void;
  onReset: () => void;
  onSave: () => void;
  showBrandLogos: boolean;
  onRestart?: () => void;
  isRestarting?: boolean;
  requiresRestartPending: boolean;
  olostepFeature?: NanobotFeatureInfo;
  olostepInstalling: boolean;
  capabilityError: string | null;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const selectedProvider =
    settings.web_search.providers.find((provider) => provider.name === form.provider) ??
    settings.web_search.providers[0];
  const { hasExistingSecret, dirty, jinaReaderDirty, missingCredential } = webSearchDraftState(settings, form);
  const effectiveJinaReader = form.useJinaReader ?? settings.web.fetch.use_jina_reader;
  const showKeyInput = webSearchProviderAcceptsApiKey(selectedProvider) && (!hasExistingSecret || keyEditing);

  useAutoSave(form, dirty, saving, onSave, !embedded && !missingCredential && (form.provider !== "olostep" || olostepFeature?.installed === true));

  return (
    <div className="settings-stack">
      <section>
        {enabled && !embedded ? <SettingsSectionTitle>{tx("settings.sections.webSearch", "Web search")}</SettingsSectionTitle> : null}
        <div hidden={!embedded && !enabled}>
        {form.provider === "olostep" && olostepFeature && !olostepFeature.installed ? (
          <div className="mb-3">
            <CapabilityInstallNotice
              title={tx("settings.capabilities.searchSupport", "Search provider support")}
              description={tx(
                "settings.capabilities.searchInstallOnSave",
                "Olostep support will be installed automatically when you save.",
              )}
              installing={olostepInstalling}
            />
          </div>
        ) : null}
        {capabilityError ? (
          <p className="mb-3 text-[12px] text-destructive">{capabilityError}</p>
        ) : null}
        </div>
        <SettingsGroup>
          <div hidden={!embedded && !enabled} className="space-y-1">
          <SettingsRow title={t("settings.byok.webSearch.provider")}>
            <ProviderPicker
              providers={settings.web_search.providers}
              value={form.provider}
              emptyLabel={t("settings.byok.webSearch.selectProvider")}
              showProviderLogos={showBrandLogos}
              onChange={onChangeProvider}
            />
          </SettingsRow>

          {selectedProvider?.credential === "none" ? (
            <SettingsRow title={t("settings.byok.webSearch.credentials")}>
              <StatusPill tone="success">{t("settings.byok.webSearch.noCredentialRequired")}</StatusPill>
            </SettingsRow>
          ) : null}

          {webSearchProviderAcceptsApiKey(selectedProvider) ? (
            <SettingsRow
              title={t("settings.byok.apiKey")}
              description={t("settings.byok.webSearch.apiKeyHelp")}
            >
              <div className="relative w-full">
                {showKeyInput ? (
                  <>
                    <Input
                      type={keyVisible ? "text" : "password"}
                      value={form.apiKey ?? ""}
                      onChange={(event) =>
                        onChangeForm((prev) => ({ ...prev, apiKey: event.target.value }))
                      }
                      placeholder={
                        hasExistingSecret
                          ? t("settings.byok.apiKeyConfiguredPlaceholder")
                          : t("settings.byok.apiKeyPlaceholder")
                      }
                      className="h-9 rounded-full pr-11 text-[13px]"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={onToggleKey}
                      aria-label={
                        keyVisible ? t("settings.byok.hideApiKey") : t("settings.byok.showApiKey")
                      }
                      className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full text-muted-foreground settings-hover hover:text-foreground"
                    >
                      {keyVisible ? (
                        <EyeOff className="h-3.5 w-3.5" aria-hidden />
                      ) : (
                        <Eye className="h-3.5 w-3.5" aria-hidden />
                      )}
                    </Button>
                  </>
                ) : (
                  <>
                    <div className="flex h-9 items-center rounded-full border border-input bg-background px-3 pr-11 text-[13px] text-muted-foreground">
                      {settings.web_search.api_key_hint ?? t("settings.byok.configuredKeyHint")}
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={onToggleKeyEditing}
                      aria-label={t("settings.actions.edit")}
                      className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 rounded-full text-muted-foreground settings-hover hover:text-foreground"
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  </>
                )}
              </div>
            </SettingsRow>
          ) : null}

          {selectedProvider?.credential === "base_url" ? (
            <SettingsRow
              title={t("settings.byok.webSearch.baseUrl")}
              description={t("settings.byok.webSearch.baseUrlHelp")}
            >
              <Input
                value={form.baseUrl ?? ""}
                onChange={(event) =>
                  onChangeForm((prev) => ({ ...prev, baseUrl: event.target.value }))
                }
                placeholder={t("settings.byok.webSearch.baseUrlPlaceholder")}
                className="h-9 w-full rounded-full text-[13px]"
              />
            </SettingsRow>
          ) : null}
          <SettingsAdvancedOptions>
          <SettingsRow title={tx("settings.rows.maxResults", "Max results")}>
            <NumberInput
              value={form.maxResults ?? settings.web_search.max_results}
              min={1}
              max={10}
              onChange={(maxResults) => onChangeForm((prev) => ({ ...prev, maxResults }))}
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.timeout", "Timeout")}>
            <NumberInput
              value={form.timeout ?? settings.web_search.timeout}
              min={1}
              max={120}
              onChange={(timeout) => onChangeForm((prev) => ({ ...prev, timeout }))}
              suffix="s"
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.jinaReader", "Jina reader")}
            description={tx("settings.help.jinaReader", "Use Jina Reader for web_fetch when available.")}
          >
            <ToggleButton
              checked={effectiveJinaReader}
              onChange={(useJinaReader) => onChangeForm((prev) => ({ ...prev, useJinaReader }))}
              ariaLabel={tx("settings.rows.jinaReader", "Jina reader")}
              label={effectiveJinaReader ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          </SettingsAdvancedOptions>
          </div>
          <RestartSettingsFooter
            error={missingCredential || Boolean(error)}
            autoSave={form.provider !== "olostep" || olostepFeature?.installed === true}
            saveLabel={t("settings.nanobotFeatures.installConfirmAction")}
            dirty={dirty}
            saving={saving}
            pendingRestart={!embedded && requiresRestartPending}
            disabled={missingCredential}
            message={
              missingCredential
                ? t("settings.byok.webSearch.missingCredential")
                : error || (!embedded && requiresRestartPending && !dirty
                  ? tx("settings.status.savedRestartApply", "Saved. Restart when ready.")
                  : jinaReaderDirty
                    ? tx("settings.status.restartAfterSaving", "Save changes, then restart when ready.")
                    : dirty
                      ? t("settings.byok.webSearch.saveHint")
                      : undefined)
            }
            onSave={onSave}
            onRestart={onRestart}
            onReset={onReset}
            isRestarting={isRestarting}
          />
        </SettingsGroup>
      </section>
    </div>
  );
}
