import { useState, type Dispatch, type SetStateAction } from "react";
import {
  ArrowUpCircle,
  Bot,
  Check,
  ChevronRight,
  ExternalLink,
  Globe2,
  HardDrive,
  ImageIcon,
  Loader2,
  Mic,
  Server,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { DEFAULT_TRANSCRIPTION_SETTINGS } from "@/components/settings/capabilities/TranscriptionSettings";
import type { SettingsSectionKey } from "@/components/settings/contracts";
import { settingsProviderConfigured } from "@/components/settings/shared/ModelControls";
import {
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
} from "@/components/settings/shared/SettingsControls";
import { TokenUsageHeatmap } from "@/components/settings/TokenUsageHeatmap";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { checkVersion } from "@/lib/api";
import type {
  FileEditDisplayMode,
  LocalActivityMode,
  LocalDensity,
  LocalPreferences,
} from "@/lib/local-preferences";
import { providerBrand, providerDisplayLabel } from "@/lib/provider-brand";
import type { SettingsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { shortWorkspacePath } from "@/lib/workspace";
import { useClient } from "@/providers/ClientProvider";

export function OverviewSettings({
  settings,
  requiresRestart,
  onSelectSection,
  showBrandLogos,
}: {
  settings: SettingsPayload;
  requiresRestart: boolean;
  onSelectSection: (section: SettingsSectionKey) => void;
  showBrandLogos: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const activePresetName = settings.agent.model_preset;
  const activePreset =
    activePresetName && activePresetName !== "default"
      ? settings.model_presets.find((preset) => preset.name === activePresetName)?.label ??
        activePresetName
      : null;
  const activeProvider = settings.agent.resolved_provider ?? settings.agent.provider;
  const activeProviderConfigured = settingsProviderConfigured(settings, activeProvider);
  const activeProviderLabel = providerDisplayLabel(settings.providers, activeProvider);
  const activeModelValue = activeProviderConfigured
    ? settings.agent.model
    : tx("settings.values.notConfigured", "Not configured");
  const activeModelCaption = activeProviderConfigured
    ? [activeProvider, activePreset].filter(Boolean).join(" · ")
    : activeProviderLabel || settings.agent.model
      ? [activeProviderLabel, settings.agent.model].filter(Boolean).join(" · ")
      : tx("settings.byok.noConfiguredProviders", "No configured providers");
  const webStatus = settings.web.enable
    ? tx("settings.values.enabled", "Enabled")
    : tx("settings.values.disabled", "Disabled");
  const webSearchProvider =
    settings.web_search.providers.find((provider) => provider.name === settings.web_search.provider) ??
    settings.web_search.providers[0];
  const webSearchProviderLabel = providerDisplayLabel(
    settings.web_search.providers,
    settings.web_search.provider,
  );
  const webSearchCredentialStatus =
    webSearchProvider?.credential === "none"
      ? tx("settings.byok.webSearch.noCredentialRequired", "No key required")
      : webSearchProvider?.credential === "optional_api_key"
        ? settings.web_search.api_key_hint
          ? tx("settings.values.configured", "Configured")
          : tx("settings.byok.webSearch.noCredentialRequired", "No key required")
      : webSearchProvider?.credential === "base_url"
        ? settings.web_search.base_url
          ? tx("settings.values.configured", "Configured")
          : tx("settings.values.notConfigured", "Not configured")
        : settings.web_search.api_key_hint
          ? tx("settings.values.configured", "Configured")
          : tx("settings.values.notConfigured", "Not configured");
  const webCaption = `${webSearchProviderLabel} · ${webSearchCredentialStatus}`;
  const imageStatus = settings.image_generation.enabled
    ? tx("settings.values.enabled", "Enabled")
    : tx("settings.values.disabled", "Disabled");
  const imageCaption = `${providerDisplayLabel(settings.image_generation.providers, settings.image_generation.provider)} · ${
    settings.image_generation.provider_configured
      ? tx("settings.values.configured", "Configured")
      : tx("settings.values.notConfigured", "Not configured")
  }`;
  const transcription = settings.transcription ?? DEFAULT_TRANSCRIPTION_SETTINGS;
  const voiceStatus = transcription.enabled
    ? tx("settings.values.enabled", "Enabled")
    : tx("settings.values.disabled", "Disabled");
  const voiceCaption = `${providerDisplayLabel(transcription.providers, transcription.provider)} · ${
    transcription.provider_configured
      ? tx("settings.values.configured", "Configured")
      : tx("settings.values.notConfigured", "Not configured")
  }`;
  const isNativeHost = (settings.surface ?? settings.runtime_surface) === "native";
  const workspaceCaption = shortWorkspacePath(settings.runtime.workspace_path);
  const runtimeTitle = isNativeHost
    ? tx("settings.rows.engine", "Engine")
    : tx("settings.rows.gateway", "Gateway");
  const runtimeValue = isNativeHost
    ? tx("settings.values.privateEngine", "Private engine")
    : `${settings.runtime.gateway_host}:${settings.runtime.gateway_port}`;
  const runtimeCaption = isNativeHost
    ? tx("settings.values.unixSocket", "Unix socket")
    : requiresRestart
      ? tx("settings.values.restartPending", "Restart pending")
      : tx("settings.values.ready", "Ready");
  return (
    <div className="space-y-7">
      <section className="rounded-[22px] bg-settings-surface px-4 py-4 sm:px-5">
        <TokenUsageHeatmap usage={settings.usage} timeZone={settings.agent.timezone} />
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.ai", "AI")}</SettingsSectionTitle>
        <SettingsGroup>
          <OverviewListRow
            icon={Bot}
            valueLogoProvider={activeProvider}
            title={tx("settings.overview.model", "Current model")}
            value={activeModelValue}
            caption={activeModelCaption}
            showBrandLogos={showBrandLogos}
            onClick={() => onSelectSection("models")}
          />
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.capabilities", "Capabilities")}</SettingsSectionTitle>
        <SettingsGroup>
          <OverviewListRow
            icon={Globe2}
            valueLogoProvider={settings.web_search.provider}
            title={tx("settings.overview.webSearch", "Web search")}
            value={webStatus}
            caption={webCaption}
            showBrandLogos={showBrandLogos}
            onClick={() => onSelectSection("browser")}
          />
          <OverviewListRow
            icon={ImageIcon}
            valueLogoProvider={settings.image_generation.provider}
            title={tx("settings.overview.imageGeneration", "Image generation")}
            value={imageStatus}
            caption={imageCaption}
            showBrandLogos={showBrandLogos}
            onClick={() => onSelectSection("image")}
          />
          <OverviewListRow
            icon={Mic}
            valueLogoProvider={transcription.provider}
            title={tx("settings.overview.voiceInput", "Voice input")}
            value={voiceStatus}
            caption={voiceCaption}
            showBrandLogos={showBrandLogos}
            onClick={() => onSelectSection("voice")}
          />
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.system", "System")}</SettingsSectionTitle>
        <SettingsGroup>
          <OverviewListRow
            icon={Server}
            title={runtimeTitle}
            value={runtimeValue}
            caption={runtimeCaption}
            onClick={() => onSelectSection("runtime")}
          />
          <OverviewListRow
            icon={HardDrive}
            title={tx("settings.overview.workspace", "Workspace")}
            value={tx("settings.values.defaultWorkspace", "Default workspace")}
            caption={workspaceCaption}
            onClick={() => onSelectSection("runtime")}
          />
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.about", "About")}</SettingsSectionTitle>
        <SettingsGroup>
          <VersionCheckRow currentVersion={settings.version?.current} />
        </SettingsGroup>
      </section>
    </div>
  );
}

function VersionCheckRow({ currentVersion }: { currentVersion?: string }) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const { token } = useClient();
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<
    | { type: "up-to-date" }
    | { type: "update"; latestVersion: string; pypiUrl?: string }
    | { type: "error"; message: string }
    | null
  >(null);

  const handleCheck = async () => {
    setChecking(true);
    setResult(null);
    try {
      const res = await checkVersion(token);
      if (res.updateAvailable) {
        setResult({
          type: "update",
          latestVersion: res.updateAvailable.latestVersion,
          pypiUrl: res.updateAvailable.pypiUrl,
        });
      } else {
        setResult({ type: "up-to-date" });
      }
    } catch (err) {
      setResult({ type: "error", message: (err as Error).message });
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="flex min-h-[62px] flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="min-w-0">
        <div className="text-[14px] font-medium leading-5 text-foreground">
          {tx("settings.about.version", "Version")}
        </div>
        <div className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
          {currentVersion ? `v${currentVersion}` : "nanobot"}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => void handleCheck()}
          disabled={checking}
          className="rounded-full"
        >
          {checking ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <ArrowUpCircle className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {checking
            ? tx("settings.about.checking", "Checking...")
            : tx("settings.about.checkForUpdates", "Check for updates")}
        </Button>
        {result?.type === "up-to-date" ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-600 dark:text-emerald-300">
            <Check className="h-3 w-3" aria-hidden />
            {tx("settings.about.upToDate", "You're up to date")}
          </span>
        ) : null}
        {result?.type === "update" ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-blue-600 dark:text-blue-300">
            <ArrowUpCircle className="h-3 w-3" aria-hidden />
            {t("settings.about.updateAvailable", {
              defaultValue: "Update available v{{version}}",
              version: result.latestVersion,
            })}
            {result.pypiUrl ? (
              <a
                href={result.pypiUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 underline-offset-2 hover:underline"
              >
                PyPI
                <ExternalLink className="h-2.5 w-2.5" aria-hidden />
              </a>
            ) : null}
          </span>
        ) : null}
        {result?.type === "error" ? (
          <span className="text-[12px] text-destructive">{result.message}</span>
        ) : null}
      </div>
    </div>
  );
}

export function AppearanceSettings({
  theme,
  onToggleTheme,
  localPrefs,
  onChangeLocalPrefs,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  localPrefs: LocalPreferences;
  onChangeLocalPrefs: Dispatch<SetStateAction<LocalPreferences>>;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className="space-y-7">
      <section>
        <SettingsSectionTitle>{t("settings.sections.interface")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow title={t("settings.rows.theme")}>
            <button
              type="button"
              onClick={onToggleTheme}
              className="inline-flex h-8 items-center rounded-full bg-muted p-0.5 text-[12px] font-medium text-muted-foreground"
            >
              <span
                className={cn(
                  "rounded-full px-3 py-1 transition-colors",
                  theme === "light" &&
                    "bg-background text-foreground ring-1 ring-inset ring-border/45",
                )}
              >
                {t("settings.values.light")}
              </span>
              <span
                className={cn(
                  "rounded-full px-3 py-1 transition-colors",
                  theme === "dark" &&
                    "bg-background text-foreground ring-1 ring-inset ring-border/45",
                )}
              >
                {t("settings.values.dark")}
              </span>
            </button>
          </SettingsRow>

          <SettingsRow title={t("settings.rows.language")}>
            <LanguageSwitcher />
          </SettingsRow>
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.localPreferences", "Local preferences")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow title={tx("settings.rows.density", "Density")}>
            <SegmentedControl
              value={localPrefs.density}
              options={[
                { value: "comfortable", label: tx("settings.values.comfortable", "Comfortable") },
                { value: "compact", label: tx("settings.values.compact", "Compact") },
              ]}
              onChange={(density) =>
                onChangeLocalPrefs((prev) => ({ ...prev, density: density as LocalDensity }))
              }
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.activityMode", "Activity detail")}>
            <SegmentedControl
              value={localPrefs.activityMode}
              options={[
                { value: "auto", label: tx("settings.values.auto", "Auto") },
                { value: "expanded", label: tx("settings.values.expanded", "Expanded") },
              ]}
              onChange={(activityMode) =>
                onChangeLocalPrefs((prev) => ({ ...prev, activityMode: activityMode as LocalActivityMode }))
              }
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.fileEditDisplay", "File edit display")}>
            <SegmentedControl
              value={localPrefs.fileEditDisplayMode}
              options={[
                { value: "summary", label: tx("settings.values.summary", "Summary") },
                { value: "diff", label: tx("settings.values.diff", "Diff") },
                { value: "collapsed_diff", label: tx("settings.values.collapsedDiff", "Collapsed diff") },
              ]}
              onChange={(fileEditDisplayMode) =>
                onChangeLocalPrefs((prev) => ({
                  ...prev,
                  fileEditDisplayMode: fileEditDisplayMode as FileEditDisplayMode,
                }))
              }
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.codeWrap", "Code wrapping")}>
            <ToggleButton
              checked={localPrefs.codeWrap}
              onChange={(codeWrap) => onChangeLocalPrefs((prev) => ({ ...prev, codeWrap }))}
              ariaLabel={tx("settings.rows.codeWrap", "Code wrapping")}
              label={localPrefs.codeWrap ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.brandLogos", "Brand logos")}
            description={tx(
              "settings.legal.thirdPartyBrands",
              "Product names, logos, and brands are property of their respective owners. Use is for identification only and does not imply endorsement.",
            )}
          >
            <ToggleButton
              checked={localPrefs.brandLogos}
              onChange={(brandLogos) => onChangeLocalPrefs((prev) => ({ ...prev, brandLogos }))}
              ariaLabel={tx("settings.rows.brandLogos", "Brand logos")}
              label={localPrefs.brandLogos ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
        </SettingsGroup>
      </section>
    </div>
  );
}

function OverviewRowIcon({
  icon: Icon,
}: {
  icon: LucideIcon;
}) {
  return (
    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[12px] bg-muted text-foreground/82 transition-colors group-hover:bg-muted/80 dark:bg-muted/70">
      <Icon className="h-4 w-4" aria-hidden />
    </span>
  );
}

function OverviewValueLogo({
  provider,
  showBrandLogos,
}: {
  provider: string | null | undefined;
  showBrandLogos: boolean;
}) {
  const brand = provider ? providerBrand(provider) : null;
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);

  if (!provider || !showBrandLogos || !brand) return null;

  if (logoUrl) {
    return (
      <span
        data-testid={`overview-logo-${provider}`}
        className="grid h-5 w-5 shrink-0 place-items-center overflow-hidden rounded-md border border-border/35 bg-background"
        aria-hidden
      >
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-3.5 w-3.5 object-contain"
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      </span>
    );
  }

  return (
    <span
      data-testid={`overview-logo-fallback-${provider}`}
      className="grid h-5 w-5 shrink-0 place-items-center rounded-md text-[7.5px] font-semibold text-white"
      style={{ backgroundColor: brand.color }}
      aria-hidden
    >
      {brand.initials}
    </span>
  );
}

function OverviewListRow({
  icon: Icon,
  valueLogoProvider,
  title,
  value,
  caption,
  showBrandLogos = false,
  onClick,
}: {
  icon: LucideIcon;
  valueLogoProvider?: string | null;
  title: string;
  value: string;
  caption: string;
  showBrandLogos?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex min-h-[68px] w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-muted/30 sm:px-5"
    >
      <OverviewRowIcon icon={Icon} />
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium leading-5 text-foreground">{title}</span>
        <span className="mt-0.5 block truncate text-[12px] leading-5 text-muted-foreground">{caption}</span>
      </span>
      <span className="ml-auto flex min-w-0 max-w-[48%] items-center gap-2">
        <OverviewValueLogo provider={valueLogoProvider} showBrandLogos={showBrandLogos} />
        <span className="truncate text-right text-[13px] leading-5 text-muted-foreground">
          {value}
        </span>
        <ChevronRight
          className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5"
          aria-hidden
        />
      </span>
    </button>
  );
}
